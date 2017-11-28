import pytest
import sqlalchemy

from sharder import Sharder

@pytest.fixture
def engine():
    engine = sqlalchemy.create_engine('sqlite:///:memory:')
    return engine

def test_single_shard(engine):
    s = Sharder(engine, 'homedir', ['nfs-a'])
    assert s.shard('yuvipanda') == 'nfs-a'
    assert s.shard('yuvipanda') == 'nfs-a'

def test_multiple_equal_shard(engine):
    buckets = [str(i) for i in range(10)]
    entries = [str(i) for i in range (100)]
    s = Sharder(engine, 'homedir', buckets)
    for e in entries:
        s.shard(e)

    shards = {}
    for e in entries:
        shard = s.shard(e)
        if shard in shards:
            shards[shard] += 1
        else:
            shards[shard] = 1

    assert len(shards) == 10
    assert sum(shards.values()) == 100
    for shard, count in shards.items():
        assert count == 10

def test_multiple_unequal_shard(engine):
    buckets = [str(i) for i in range(10)]
    entries = [str(i) for i in range (99)]
    s = Sharder(engine, 'homedir', buckets)
    for e in entries:
        s.shard(e)

    shards = {}
    for e in entries:
        shard = s.shard(e)
        if shard in shards:
            shards[shard] += 1
        else:
            shards[shard] = 1

    assert len(shards) == 10
    assert sum(shards.values()) == 99
    assert sorted(shards.values()) == [9, 10, 10, 10, 10, 10, 10, 10, 10, 10]
