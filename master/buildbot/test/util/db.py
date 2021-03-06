# This file is part of Buildbot.  Buildbot is free software: you can
# redistribute it and/or modify it under the terms of the GNU General Public
# License as published by the Free Software Foundation, version 2.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE.  See the GNU General Public License for more
# details.
#
# You should have received a copy of the GNU General Public License along with
# this program; if not, write to the Free Software Foundation, Inc., 51
# Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Copyright Buildbot Team Members

import os
from sqlalchemy.schema import MetaData
from twisted.python import log
from twisted.internet import defer
from buildbot.db import model, pool, enginestrategy

class RealDatabaseMixin(object):
    """
    A class that sets up a real database for testing.  This sets self.db_url to
    the URL for the database.  By default, it specifies an in-memory SQLite
    database, but if the BUILDBOT_TEST_DB_URL environment variable is set, it
    will use the specified database, being careful to clean out *all* tables in
    the database before and after the tests are run - so each test starts with
    a clean database.

    @ivar db_pool: a (real) DBThreadPool instance that can be used as desired

    @ivar db_url: the DB URL used to run these tests

    @ivar db_engine: the engine created for the test database
    """

    # Note that this class uses the production database model.  A
    # re-implementation would be virtually identical and just require extra
    # work to keep synchronized.

    # Similarly, this class uses the production DB thread pool.  This achieves
    # a few things:
    #  - affords more thorough tests for the pool
    #  - avoids repetitive implementation
    #  - cooperates better at runtime with thread-sensitive DBAPI's

    def __thd_clean_database(self, engine):
        # drop the known tables
        model.Model.metadata.drop_all(bind=engine, checkfirst=True)

        # see if we can find any other tables to drop
        meta = MetaData(bind=engine)
        meta.reflect()
        meta.drop_all()

    def setUpRealDatabase(self, basedir='basedir', want_pool=True):
        """

        Set up a database.  Ordinarily sets up an engine and a pool and takes
        care of cleaning out any existing tables in the database.  If
        C{want_pool} is false, then no pool will be created, and the database
        will not be cleaned.

        @param basedir: (optional) basedir for the engine
        @param want_pool: false to not create C{self.db_pool}
        @returns: Deferred
        """
        self.__want_pool = want_pool

        memory = 'sqlite://'
        self.db_url = os.environ.get('BUILDBOT_TEST_DB_URL',
                ### XXX TEMPORARY until sqlalchemification is complete
                'sqlite:///%s' % (os.path.abspath('test.db')))
        self.__using_memory_db = (self.db_url == memory)

        self.db_engine = enginestrategy.create_engine(self.db_url,
                                                    basedir=basedir)

        # if the caller does not want a pool, we're done.
        if not want_pool:
            return defer.succeed(None)

        self.db_pool = pool.DBThreadPool(self.db_engine)

        log.msg("cleaning database %s" % self.db_url)
        return self.db_pool.do_with_engine(self.__thd_clean_database)

    def tearDownRealDatabase(self):
        if self.__want_pool:
            return self.db_pool.do_with_engine(self.__thd_clean_database)
        else:
            return defer.succeed(None)

    def insertTestData(self, rows, tables=[]):
        """Insert test data into the database for use during the test.

        @param rows: be a sequence of L{fakedb.Row} instances.  These will be
        sorted by table dependencies, so order does not matter.

        @param tables: optional list of names of tables to create, but into
        which no data is inserted.  This is equivalent ot calling
        L{createTestTables}.

        @returns: Deferred
        """
        # sort the tables by dependency
        all_table_names = set([ row.table for row in rows ] + tables)
        ordered_tables = [ t for t in model.Model.metadata.sorted_tables
                           if t.name in all_table_names ]
        def thd(engine):
            # create tables -- in order
            for tbl in ordered_tables:
                tbl.create(bind=engine, checkfirst=True)

                # insert all rows for this table
                for row in [ r for r in rows if r.table == tbl.name ]:
                    tbl = model.Model.metadata.tables[row.table]
                    try:
                        tbl.insert(bind=engine).execute(row.values)
                    except:
                        log.msg("while inserting %s - %s" % (row, row.values))
                        raise
        return self.db_pool.do_with_engine(thd)

    def createTestTables(self, tables):
        """Create a set of tables, but do not insert data into them.

        @param tables: list of names of tables to create, but into which no
        data is inserted.

        @returns: Deferred
        """
        all_table_names = set(tables)
        ordered_tables = [ t for t in model.Model.metadata.sorted_tables
                           if t.name in all_table_names ]
        def thd(engine):
            for tbl in ordered_tables:
                tbl.create(bind=engine, checkfirst=True)
        return self.db_pool.do_with_engine(thd)
