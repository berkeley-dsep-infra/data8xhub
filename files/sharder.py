import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, UniqueConstraint, func, Index
from sqlalchemy.orm import sessionmaker
import psycopg2.pool

Base = declarative_base()

class Entry(Base):
    __tablename__ = 'entries'

    id = Column(Integer, primary_key=True)
    name = Column(String)
    kind = Column(String)
    bucket = Column(String)

    # No two items of same name and kind can exist
    name_kind_constraint = UniqueConstraint('name', 'kind')

    # Indexes for supporting the specific kinds of queries we are most likely to do
    name_kind_index = Index('name', 'kind')
    bucket_index = Index('bucket')



class Sharder:
    """
    Simple db based sharder.

    Does least-loaded balancing of a given kind of object (homedirectory, running user, etc)
    across multiple buckets, ensuring that once an object is assigned to a bucket it always
    is assigned to the same bucket.
    """
    SCHEMA = """
    CREATE TABLE IF NOT EXISTS entries_v1 (
        id      SERIAL PRIMARY KEY NOT NULL,
        kind    TEXT NOT NULL,
        bucket  TEXT NOT NULL,
        name    TEXT NOT NULL,
        UNIQUE (kind, name)
    );
    CREATE INDEX IF NOT EXISTS entries_v1_kind_name_index ON entries_v1 (kind, name);
    """
    def __init__(self, hostname, username, password, dbname, kind, buckets, log):
        self.buckets = buckets
        self.kind = kind
        self.log = log

        self.pool = psycopg2.pool.ThreadedConnectionPool(1, 4, user=username, host=hostname, password=password, dbname=dbname)
        with self.pool.getconn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(self.SCHEMA)
                    conn.commit()

                    # Make sure that we have at least one dummy entry for each fileserver
                    for bucket in buckets:
                        cur.execute("""
                        INSERT INTO entries_v1(kind, bucket, name)
                        VALUES(%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """, (self.kind, bucket, f'dummy-{bucket}'))
                        conn.commit()
            finally:
                self.pool.putconn(conn)

    def shard(self, name):
        """
        Return the bucket where name should be placed.

        If it already isn't in the database, a new entry will be created in the database,
        placing it in the currently least populated bucket.
        """
        with self.pool.getconn() as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute("""
                    SELECT bucket FROM entries_v1
                    WHERE kind=%s AND name=%s
                    LIMIT 1
                    """, (self.kind, name))
                    row = cur.fetchone()
                    if row:
                        bucket = row[0]
                        self.log.info(f'Found {name} sharded to bucket {bucket}')
                        return bucket

                    # Insert the data!
                    cur.execute("""
                    INSERT INTO entries_v1 (name, kind, bucket)
                    VALUES(
                        %s,
                        %s,
                        (SELECT bucket FROM entries_v1 WHERE kind=%s GROUP BY bucket ORDER BY count(bucket) LIMIT 1)
                    ) RETURNING bucket;
                    """, (name, self.kind, self.kind))
                    conn.commit()
                    bucket = cur.fetchone()[0]
                    self.log.info(f'Sharded {name} to bucket {bucket}')
                    return bucket
            finally:
                self.pool.putconn(conn)