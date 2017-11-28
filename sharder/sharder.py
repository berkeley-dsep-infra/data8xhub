import sqlalchemy
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, Integer, String, UniqueConstraint, func, Index
from sqlalchemy.orm import sessionmaker

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
    def __init__(self, engine, kind, buckets):
        self.engine = engine
        self.buckets = buckets
        self.kind = kind
        Base.metadata.create_all(self.engine)

    def shard(self, name):
        """
        Return the bucket where name should be placed.

        If it already isn't in the database, a new entry will be created in the database,
        placing it in the currently least populated bucket.
        """
        s = sessionmaker(bind=self.engine)()
        entry = s.query(Entry).filter(Entry.kind==self.kind).filter(Entry.name==name).one_or_none()
        if entry:
            return entry.bucket
        else:
            return self._create_entry(s, name)

    def _create_entry(self, session, name):
        """
        Create an entry for name in the bucket currently least populated
        """
        bucket_counts = session.query(Entry.bucket, func.count('*').label('entries'))\
                               .filter(Entry.kind==self.kind)\
                               .group_by(Entry.bucket).all()

        all_bucket_counts = {b: 0 for b in self.buckets}

        # It's possible there exist buckets that don't have any entries
        for bucket, entries_count in bucket_counts:
            if bucket in all_bucket_counts:
                all_bucket_counts[bucket] = entries_count

        top_bucket = sorted(all_bucket_counts.items(), key=lambda i: i[1])[0][0]

        e = Entry(name=name, kind=self.kind, bucket=top_bucket)
        session.add(e)
        session.commit()
        return top_bucket
