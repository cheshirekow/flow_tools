"""Contains Object Relational Model for flow-tools daemons."""

import sys
import sqlalchemy

from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import DateTime
from sqlalchemy import UniqueConstraint

# A sqlalchemy concept, a kind of 'registry' of the SQL object mapping
Base = declarative_base()  # pylint: disable=invalid-name


class GerritJira(Base):  # pylint: disable=no-init
  """
  Stores state of gerrit jira integration sync.
  """

  __tablename__ = 'gerrit_jira_map'
  __table_args__ = (UniqueConstraint('changeid', 'issue', name='u_map'),
                    {'sqlite_autoincrement': True})

  rid = Column(Integer, primary_key=True)

  # The jira issue key.
  issue = Column(String)

  # The gerrit change id.
  changeid = Column(String)

  def __repr__(self):
    return ('<GerritJira(issue="{}", changeid="{}")>'
            .format(self.issue, self.changeid))


class GerritJiraTrans(Base):  # pylint: disable=no-init
  """
  Log entry of a transition actually performed
  """

  __tablename__ = 'gerrit_jira_log'
  __table_args__ = {'sqlite_autoincrement': True}

  rid = Column(Integer, primary_key=True)

  # When we performed the transition
  time = Column(DateTime)

  # The jira issue key.
  issue = Column(String)

  # Name of the start state
  from_status = Column(String)

  # Name of the end state
  to_status = Column(String)

  def __repr__(self):
    return ('<GerritJiraEvent(issue="{}",from="{}",to="{}")>'
            .format(self.issue, self.from_status, self.to_status))

class PollHistory(Base): # pylint: disable=no-init
  """
  Stores a history of poll jobs that we've issued against gerrit. This allows
  us to maintain
  """

  __tablename__ = 'poll_history'
  __table_args__ = {'sqlite_autoincrement': True}

  rid = Column(Integer, primary_key=True)

  # The start of the period we are querying changes over
  period_start = Column(DateTime)

  # The end of the period we are querying changes over. This defaults to the
  # current time on the host system, which hopefully is accurate.
  period_end = Column(DateTime)

  # Zero indicates that the poll was successful
  status = Column(Integer)





def init_sql(database_url):
  """
  Initialize sqlalchemy and the sqlite database. Returns a session factory
  """

  engine = sqlalchemy.create_engine(database_url, echo=False)
  try:
    Base.metadata.create_all(engine)
  except:
    sys.stderr.write('database_url: {}\n'.format(database_url))
    raise
  return sqlalchemy.orm.sessionmaker(bind=engine)
