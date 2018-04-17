#!/usr/bin/python
# PYTHON_ARGCOMPLETE_OK
"""
Command line client to automate parts of our agile workflow.
"""

from __future__ import print_function
import argparse
import datetime
import io
import inspect
import logging
import os
import re
import sys
import textwrap

import flow_tools
from flow_tools import orm
from flow_tools import gerrit_util
from flow_tools import git_util
from flow_tools import integrations
from flow_tools import jira_util


class Configuration(object):
  def __init__(self, db_url=None, jira=None, gerrit=None, gerrit_jira=None,
               git=None, **extra):
    self.db_url = db_url
    self.jira = jira_util.Configuration(**jira)
    self.gerrit = gerrit_util.Configuration(**gerrit)
    self.gerrit_jira = integrations.GerritJiraConfig(**gerrit_jira)
    self.git = git_util.Configuration(**git)

    for key in extra:
      if key.startswith('_'):
        continue
      logging.warn("Unused config option: %s", key)


def print_header(header, char=None):
  """
  Print a header with horizontal rule
  """
  if char is None:
    char = '='

  sys.stdout.write(header)
  sys.stdout.write('\n')
  sys.stdout.write(char*len(header))
  sys.stdout.write('\n')

def class_to_cmd(name):
  intermediate = re.sub('(.)([A-Z][a-z]+)', r'\1-\2', name)
  return re.sub('([a-z0-9])([A-Z])', r'\1-\2', intermediate).lower()


class Command(object):
  """
  Base class making it a little easier to set up a complex argparse tree by
  specifying features of a command as memebers of a class.
  """

  @staticmethod
  def setup_parser(subparser):
    """
    Coonfigure subparser for this command. Override in subclasses.
    """
    pass

  @classmethod
  def get_cmd(cls):
    """
    Return a string command name formulated by de-camael-casing the class
    name.
    """
    return class_to_cmd(cls.__name__)

  @classmethod
  def add_parser(cls, subparsers):
    """
    Add a subparser to the list of subparsers, and then call the classmethod
    to configure that subparser.
    """

    subparser = subparsers.add_parser(cls.get_cmd(), help=cls.__doc__)
    cls.setup_parser(subparser)

  @classmethod
  def run_args(cls, sql, args):  # pylint: disable=unused-argument
    """
    Override this method to execute the command with the given parsed args.
    """
    raise RuntimeError('run_args unimplemented for object of type {}'
                       .format(getattr(cls, '__name__', '??')))


class AddMentionsToWatchers(Command):
  """Get a list of all mentioned users in the issue comments and description,
     and add any to the watcher list that are not already watchers."""

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('issue_keys', nargs='+')

  @classmethod
  def run_args(cls, config, args):
    jira_client = jira_util.get_jira(**config.jira.auth)

    for issue_key in args.issue_keys:
      issue = jira_client.issue(issue_key)
      jira_util.add_mentions_to_watchers(jira_client, issue)


class CloseIssuesMerged(Command):
  """
  Walk the list of merges on master for the given user. Look for tags in
  the commit message indicating that the commit closes/resolves an
  issue. Then login to jira and close those issues if they are not
  already closed.
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('-r', '--repo-path', default=os.getcwd(),
                        help='Path to the repository')
    parser.add_argument('-m', '--max-commits', default=100,
                        help='Don\'t inspect more than this many commits')

  @classmethod
  def run_args(cls, config, args):
    jira_client = jira_util.get_jira(**config.jira.auth)
    tag_map = config.gerrit_jira.tag_map
    integrations.close_issues_with_merged_resolutions(
        jira_client, args.repo_path, tag_map, branch='master',
        max_commits=args.max_commits)

GERRIT_TIME_FMT = "%Y-%m-%d %H:%M:%S"


class UpdateJiraFromGerrit(Command):
  """
  Monitor changes on gerrit for tags indicating associated issues that are
  resolved by those changes. As a change moves through the gerrit workflow,
  move the associated issue through the jira workflow.
  """

  @staticmethod
  def setup_parser(parser):
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(weeks=1)
    week_ago_str = week_ago.strftime(GERRIT_TIME_FMT)
    now_str = now.strftime(GERRIT_TIME_FMT)

    parser.add_argument('-p', '--project', required=True,
                        help='what project to sync')
    parser.add_argument('-s', '--start-time', default=week_ago_str,
                        help='scan for changes starting at this time')
    parser.add_argument('-e', '--end-time', default=now_str,
                        help='scan for changes ending at this time')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help="do all the work except don't actually update"
                             " jira.")

  @classmethod
  def run_args(cls, config, args):
    jira_client = jira_util.get_jira(**config.jira.auth)
    gerrit_client = gerrit_util.get_gerrit(**config.gerrit.rest)
    session_factory = orm.init_sql(config.db_url)

    nominal_flow = config.jira.nominal_flow
    tag_map = config.gerrit_jira.tag_map

    integrations.update_issues_from_review(
        gerrit_client, jira_client, session_factory(), args.project,
        args.start_time, args.end_time, args.dry_run, nominal_flow, tag_map)


class IncrementJiraFromGerrit(Command):
  """
  Monitor changes on gerrit for tags indicating associated issues that are
  resolved by those changes. As a change moves through the gerrit workflow,
  move the associated issue through the jira workflow.

  Same as update-jira-from-gerrit but in this case the start of the period to
  search will the last successful time we ran this command, and the end time
  will be right now.
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('-p', '--project', required=True,
                        help='what project to sync')
    parser.add_argument('-d', '--dry-run', action='store_true',
                        help="do all the work except don't actually update"
                             " jira.")

  @classmethod
  def run_args(cls, config, args):
    jira_client = jira_util.get_jira(**config.jira.auth)
    gerrit_client = gerrit_util.get_gerrit(**config.gerrit.rest)
    session_factory = orm.init_sql(config.db_url)

    nominal_flow = config.jira.nominal_flow
    tag_map = config.gerrit_jira.tag_map

    sql = session_factory()

    end_time = datetime.datetime.utcnow()

    # If the database contains nothing, then default to 1 week ago
    start_time = end_time - datetime.timedelta(weeks=1)

    query = (sql
             .query(orm.PollHistory)
             .filter_by(status=0)
             .order_by(orm.PollHistory.rid.desc())
             .slice(0, 1))
    for record in query:
      start_time = record.period_end

    print('\n\nPolling gerrit at {} UTC\n{}'.format(end_time, '-'*60))
    record = orm.PollHistory(period_start=start_time, period_end=end_time,
                             status=-1)

    try:
      integrations.update_issues_from_review(
          gerrit_client, jira_client, sql, args.project,
          start_time.strftime(GERRIT_TIME_FMT),
          end_time.strftime(GERRIT_TIME_FMT),
          args.dry_run, nominal_flow, tag_map)
      record.status = 0
    except:
      raise
    finally:
      if not args.dry_run:
        sql.add(record)
        sql.commit()


class PrintReleases(Command):
  """
  Parse tags on the gerrit remote and print a sorted list of version strings,
  using the pattern and sort functions from the config file.
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('repo_path', help='Path to the git repository')

  @classmethod
  def run_args(cls, config, args):
    for version in git_util.get_releases(args.repo_path, config):
      sys.stdout.write(version)
      sys.stdout.write('\n')

class IssuesInRelease(Command):
  """
  Show a list of issues that were closed in a release. In particular, lookup
  all commits that went into a release (since the common ancestor with the
  previous release). For each commit, get the list of issues closed or resolved
  through commit message meta data. These are the issues considered "in" the
  release.
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('repo_path', help='Path to the git repository')
    parser.add_argument('release', nargs='?', default=None,
                        help='If specified, show only this release')
    parser.add_argument('--url', action='store_true', help='output as urls')

  @classmethod
  def run_args(cls, config, args):
    import jira
    jira_client = jira_util.get_jira(**config.jira.auth)
    releases = git_util.get_releases(args.repo_path, config)
    pairs = zip(releases[0:-1], releases[1:])
    if args.url:
      wrapper = textwrap.TextWrapper(width=80, initial_indent=' '*4,
                                     subsequent_indent=' '*4)
    else:
      wrapper = textwrap.TextWrapper(width=80, initial_indent='',
                                     subsequent_indent=' '*11)


    for from_tag, to_tag in pairs:
      if args.release is not None and to_tag != args.release:
        continue

      print_header('{} -> {}'.format(from_tag, to_tag))
      issues = git_util.get_issues_closed_in_series(
          args.repo_path, from_tag, to_tag, config.gerrit_jira.tag_map)
      for issue in issues:
        try:
          issue_obj = jira_client.issue(issue, 'summary')
        except jira.JIRAError:
          sys.stdout.write('{}: N/A\n'.format(issue))
          continue

        if args.url:
          sys.stdout.write('{}/browse/{}\n'
                           .format(config.jira.auth['url'], issue))
          sys.stdout.write(wrapper.fill(issue_obj.fields.summary))
          sys.stdout.write('\n')
        else:
          text = wrapper.fill('{}: {}'
                              .format(issue, issue_obj.fields.summary))
          sys.stdout.write(text)
          sys.stdout.write('\n')


class SetIssuesFixedInRelease(Command):
  """
  For each issue closed in a release, set the "Fixed Release" field of jira
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('repo_path', help='Path to the git repository')
    parser.add_argument('release', nargs='?', default=None,
                        help='If specified, show only this release')

  @classmethod
  def run_args(cls, config, args):
    import jira
    jira_client = jira_util.get_jira(**config.jira.auth)
    releases = git_util.get_releases(args.repo_path, config)
    pairs = zip(releases[0:-1], releases[1:])

    for from_tag, to_tag in pairs:
      if args.release is not None and to_tag != args.release:
        continue

      print_header('{} -> {}'.format(from_tag, to_tag))
      issues = git_util.get_issues_closed_in_series(
          args.repo_path, from_tag, to_tag, config.gerrit_jira.tag_map)
      for issue in issues:
        try:
          issue_obj = jira_client.issue(issue, config.jira.fixed_release_field)
          issue_obj.update(fields={config.jira.fixed_release_field :to_tag})
          sys.stdout.write('  {}: {}\n'.format(issue, to_tag))
        except jira.JIRAError:
          sys.stdout.write('  {}: failed (non-existant?)\n'.format(issue))
          continue

class ChangesInRelease(Command):
  """
  Show a list of commit message summaries for each commit in the series between
  one version and another.
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('repo_path', help='Path to the git repository')
    parser.add_argument('release', nargs='?', default=None,
                        help='If specified, show only this release')

  @classmethod
  def run_args(cls, config, args):
    releases = git_util.get_releases(args.repo_path, config)
    pairs = zip(releases[0:-1], releases[1:])
    for from_tag, to_tag in pairs:
      if args.release is not None and to_tag != args.release:
        continue
      print_header('{} -> {}'.format(from_tag, to_tag))
      summaries = git_util.get_release_notes(args.repo_path, from_tag, to_tag)
      for summary in summaries:
        sys.stdout.write(summary)
        sys.stdout.write('\n')


class ReleaseNotes(Command):
  """
  Combines issues-in-release and changes-in-release into a single output
  """

  @staticmethod
  def setup_parser(parser):
    parser.add_argument('repo_path', help='Path to the git repository')
    parser.add_argument('release', nargs='?', default=None,
                        help='If specified, show only this release')
    parser.add_argument('--url', action='store_true', help='output as urls')

  @classmethod
  def run_args(cls, config, args):
    import jira
    jira_client = jira_util.get_jira(**config.jira.auth)
    releases = git_util.get_releases(args.repo_path, config)
    pairs = zip(releases[0:-1], releases[1:])
    if args.url:
      wrapper = textwrap.TextWrapper(width=80, initial_indent=' '*4,
                                     subsequent_indent=' '*4)
    else:
      wrapper = textwrap.TextWrapper(width=80, initial_indent='',
                                     subsequent_indent=' '*11)


    for from_tag, to_tag in pairs:
      if args.release is not None and to_tag != args.release:
        continue
      print_header('{} -> {}'.format(from_tag, to_tag))
      sys.stdout.write('\n')
      issues = git_util.get_issues_closed_in_series(
          args.repo_path, from_tag, to_tag, config.gerrit_jira.tag_map)
      summaries = git_util.get_release_notes(args.repo_path, from_tag, to_tag)

      for issue in issues:
        try:
          issue_obj = jira_client.issue(issue, 'summary')
        except jira.JIRAError:
          sys.stdout.write('{}: N/A\n'.format(issue))
          continue

        if args.url:
          sys.stdout.write('{}/browse/{}\n'
                           .format(config.jira.auth['url'], issue))
          sys.stdout.write(wrapper.fill(issue_obj.fields.summary))
          sys.stdout.write('\n')
        else:
          text = wrapper.fill('{}: {}'
                              .format(issue, issue_obj.fields.summary))
          sys.stdout.write(text)
          sys.stdout.write('\n')

      if issues and summaries:
        sys.stdout.write('\n')

      for summary in summaries:
        sys.stdout.write(summary)
        sys.stdout.write('\n')


def get_config(config_path):
  try:
    with io.open(config_path, 'r', encoding='utf-8') as infile:
      config_dict = {}
      exec(infile.read(), config_dict)  # pylint: disable=W0122
      return config_dict
  except (IOError, OSError):
    return {}

def iter_command_classes():
  """
  Return a list of all Command subclasses in this file.
  """

  for _, cmd_class in globals().iteritems():
    if (inspect.isclass(cmd_class)
            # pylint: disable=bad-continuation
            and issubclass(cmd_class, Command)
            and cmd_class is not Command):
      yield cmd_class

HELP_EPILOG = """
Subcommands have their own options. Use <command> -h or <command> --help to
see specific help for each subcommand.
"""

def main(argv=None):
  if argv is None:
    argv = sys.argv[1:]

  format_str = '%(filename)s:%(lineno)-3s: [%(levelname)-8s] %(message)s'
  logging.basicConfig(level=logging.INFO,
                      format=format_str,
                      datefmt='%Y-%m-%d %H:%M:%S',
                      filemode='w')

  parser = argparse.ArgumentParser(prog="flow-tools", description=__doc__,
                                   epilog=HELP_EPILOG)
  parser.add_argument('-c', '--config',
                      default=os.path.expanduser('~/.flowtools/config.py'))
  parser.add_argument('-v', '--version', action='version',
                      version=flow_tools.VERSION)
  subparsers = parser.add_subparsers(dest='command', metavar='<command>')


  commands = [init() for init in iter_command_classes()]
  for command in commands:
    command.add_parser(subparsers)

  try:
    import argcomplete
    argcomplete.autocomplete(parser)
  except ImportError:
    pass
  args = parser.parse_args(argv)

  config = Configuration(**get_config(args.config))

  for command in commands:
    if args.command == command.get_cmd():
      return command.run_args(config, args)

if __name__ == '__main__':
  sys.exit(main(sys.argv[1:]))
