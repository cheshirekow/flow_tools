"""
Functions that perform integration tasks between one or more of:

  * A local git repo
  * A gerrit instance
  * A jira instance
"""

import datetime
import logging
import jira

from flow_tools import git_util
from flow_tools import orm
from flow_tools import jira_util
from flow_tools import gerrit_util

class GerritJiraConfig(object):
  def __init__(self, tag_map):
    self.tag_map = tag_map

def make_resolution_message(commit):
  """Create a string to post as the resolution message when resolving a change
     due to a commit merged into master."""

  change_id = gerrit_util.get_gerrit_change_id(commit)

  if change_id is not None:
    return """
Automatically generated message:

This issue was resolved by {} in commit {}.
See: https://gerrit.skyd.io/#/q/{}
""".format(str(commit.author), commit.hexsha, change_id)

  else:
    return """
Automatically generated message:

This issue was resolved by {} in commit {}, however I was unable to determine
a gerrit change id for that change.
""".format(str(commit.author), commit.hexsha)

def close_issues_with_merged_resolutions(jira_client, repo_path, tag_map,
                                         branch='master', max_commits=10):
  """Walk through a list of commits to a given branch and look for commit
     message tags marking issue resolutions. For each issue that is resolved,
     update it's status in jira."""

  iter_count = 0
  resolve_to = None
  for jira_res in jira_client.resolutions():
    if jira_res.name == 'Done':
      resolve_to = jira_res

  assert resolve_to is not None
  resolve_to = dict(id=resolve_to.id)

  for commit, resolutions in (
      git_util.get_merges_that_close_issues(tag_map, repo_path, branch)):
    for issue_key, resolution in resolutions.iteritems():
      try:
        issue = jira_client.issue(issue_key, 'status')
      except jira.JIRAError:
        continue

      if issue.fields.status.name != resolution:
        tid, available_states = jira_util.get_transition_to(
            jira_client, issue, resolution)
        if tid is None:
          logging.warn(
              'commit %s resolves issue %s as %s but I can find'
              ' no transition to that state. Available states: %s, current'
              ' state: %s', commit.hexsha, issue_key, resolution,
              ','.join(sorted(available_states)), issue.fields.status.name)
          continue

        logging.info('Resolving %s to %s using transition %s due to commit %s',
                     issue_key, resolution, tid, commit.hexsha)
        jira_client.transition_issue(issue, tid, resolution=resolve_to)
        message = make_resolution_message(commit)
        jira_client.add_comment(issue, message)

    iter_count += 1
    if iter_count > max_commits:
      break


def get_jira_status_from_changeinfo(changeinfo):
  """
  Determine the corresponding jira status of an issue that is resolved by the
  given change. For example, if this change "Closes" issue R1-1234, and the
  change is in review, then the jira status is "In Review". If the change has
  been merged then the jira status is "Closed".
  """

  # this change was abandoned, we can't infer jira state from it
  if changeinfo['status'] == 'ABANDONED':
    return None
  elif changeinfo['status'] == 'MERGED':
    return 'Resolved'
  elif changeinfo['status'] == 'DRAFT':
    return 'In Progress'
  else:  # == 'NEW'
    return 'In Review'


def make_jira_message(changeinfo, goal_state):
  """
  Create a string to post as a message when transitioning a jira issue
  due to a commit moving through gerrit.
  """

  fmtargs = dict(
      goal_state=goal_state,
      owner='{name} <{email}>'.format(**changeinfo['owner']),
      branch=changeinfo.get('branch', '?'),
      current_revision=changeinfo['current_revision'],
      change_id=changeinfo['change_id']
  )

  return """
Automatically generated message:

This issue was advanced to {goal_state} due to a gerrit change
by {owner} on branch {branch} currently at commit
{current_revision}.
See: https://gerrit.skyd.io/#/q/{change_id}
""".format(**fmtargs)


def update_issues_from_review(gerrit_client, jira_client, sql,
                              project, start_time, end_time, dry_run,
                              nominal_flow, tag_map):
  """
  Query gerrit for any changes which are modified in the time period specified,
  check any issues that are mapped to those changes through the commit messge,
  if the status of the change in gerrit suggests a status change of the issue
  then update that issue status to match.
  """
  # pylint: disable=too-many-statements

  resolve_to = None
  for jira_res in jira_client.resolutions():
    if jira_res.name == 'Done':
      resolve_to = jira_res

  assert resolve_to is not None
  resolve_to = dict(id=resolve_to.id)

  offset = 0
  has_more_changes = True
  while has_more_changes:
    response = gerrit_util.get_changes_from_range(
        gerrit_client, project, start_time, end_time, offset)
    for changeinfo in response:
      print('{} : {}'.format(changeinfo.get('change_id', '??'),
                             changeinfo.get('status', '??')))

      if changeinfo['status'] == 'ABANDONED':
        # Delete any database records for the abandoned change
        (sql
         .query(orm.GerritJira)
         .filter_by(changeid=changeinfo['change_id'])
         .delete())
        continue

      change_meta = gerrit_util.get_message_meta(
          gerrit_client, changeinfo['change_id'],
          changeinfo['current_revision'])
      resolutions = []
      for key in ['Closes', 'Resolves']:
        for issue in change_meta[key]:
          resolutions.append((issue, tag_map[key]))

      for issue_key, resolution in resolutions:
        try:
          issue = jira_client.issue(issue_key, 'status')
        except jira.JIRAError:
          logging.warn('  %s: \n    not an issue', issue_key)
          continue

        # If we have not yet associated this change with this issue, than
        # add an association.
        if (sql
            .query(orm.GerritJira)
            .filter_by(issue=issue_key, changeid=changeinfo['change_id'])
            .count()) == 0:
          record = orm.GerritJira(issue=issue_key,
                                  changeid=changeinfo['change_id'])
          sql.add(record)
          sql.commit()

        if changeinfo['status'] == 'MERGED':
          goal_state = resolution
        # TODO(josh): or number of reviewers other than the owner and jenkins
        # is zero
        elif changeinfo['status'] == 'DRAFT':
          goal_state = 'In Progress'
        else:
          goal_state = 'In Review'

        logging.info('  %s: %s -> %s', issue_key, issue.fields.status.name,
                     goal_state)

        # If the change would be a backward movement in the nominal flow,
        # then, don't advance it
        if '-' not in issue.key:
          logging.warn('    issue does not have a prefix: %s', issue_key)
          continue

        project_key = issue.key.split('-')[0]
        if not jira_util.is_nominal_transition(
            nominal_flow.get(project_key, {}),
            issue.fields.status.name, goal_state):
          logging.info('    skipping transition, non-forward flow')
          continue

        # If there is more than one change associated with the given issue,
        # then disble transition
        if sql.query(orm.GerritJira).filter_by(issue=issue_key).count() > 1:
          logging.info('    skipping transition, multiple active commits')
          continue

        tid, available_states = jira_util.get_transition_to(
            jira_client, issue, goal_state)
        if tid is None:
          logging.info('    missing transition, Available states: {}'
                       .format(','.join(sorted(available_states))))
          continue

        if dry_run:
          logging.info('    skipping transition: dry-run')
          continue

        message = make_jira_message(changeinfo, goal_state)
        if goal_state in tag_map.values():
          try:
            jira_client.transition_issue(issue, tid, resolution=resolve_to)
            jira_client.add_comment(issue, message)
          except jira.exceptions.JIRAError:
            # NOTE(josh): for now, just ignore. This is the case of someone
            # marking a change as `Closes` but then manually putting it to
            # `Resolved`.
            logging.warn('spoofing transition due to JIRA error')
        else:
          jira_client.transition_issue(issue, tid)
          jira_client.add_comment(issue, message)

        log_event = orm.GerritJiraTrans(time=datetime.datetime.utcnow(),
                                        issue=issue_key,
                                        from_status=issue.fields.status.name,
                                        to_status=goal_state)
        sql.add(log_event)
        sql.commit()

    if len(response) > 0 and response[-1].get('_more_changes', False):
      has_more_changes = True
      offset += len(response)
    else:
      has_more_changes = False
