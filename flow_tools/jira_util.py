"""
Functions for communicating with a jira instance
"""

import logging
import re

import jira

class AuthConfig(object):
  def __init__(self, url, username, password):
    self.url = url
    self.username = username
    self.password = password

class Configuration(object):
  def __init__(self, auth, fixed_release_field, nominal_flow):
    self.auth = auth
    self.fixed_release_field = fixed_release_field
    self.nominal_flow = nominal_flow

def get_jira(url, username, password, **_):
  """
  Return a jira rest client object based on the configuration.
  """
  return jira.JIRA(url, basic_auth=(username, password))


def get_transition_to(jira_client, issue, target_state):
  """
  Query jira to find a list of available transitions. Match the end state name
  of those transitions against the string `target_state`. Return the transition
  id that reaches the target state if found, or None if not.

  Returns a tuple (tid, available_states)
  """

  tid = None
  available_states = []
  for transition in jira_client.transitions(issue):
    # NOTE(josh): OMG,WTF,jira appears to have changed their output from
    # <from_state> : <to_state>
    # to
    # <from_state> -> <to_state>
    if ':' in transition['name']:
      tstate = transition['name'].split(':', 1)[1].strip()
    elif '->' in transition['name']:
      tstate = transition['name'].split('->', 1)[1].strip()
    else:
      logging.warn("Expected ':' or '->' in %s", transition['name'])
      continue

    available_states.append(tstate)
    if tstate == target_state:
      tid = transition['id']

  return tid, available_states


USER_RE = re.compile(r"\[~(?P<user>[^\]]+)\]")

def get_mentioned_user_set(jira_client, issue):
  """Return a set of users mentioned in the issue description or comments."""
  user_set = set()

  if issue.fields.description is not None:
    for user in USER_RE.findall(issue.fields.description):
      user_set.add(user)

  for comment in jira_client.comments(issue):
    for user in USER_RE.findall(comment.body):
      user_set.add(user)

  return user_set


def get_watcher_user_set(jira_client, issue):
  """Get a list of users ids that are watchers."""
  user_set = set()

  watchlist = jira_client.watchers(issue)
  for watcher in watchlist.watchers:
    user_set.add(watcher.name)

  return user_set


def get_nonwatcher_mentions(jira_client, issue):
  """Get a list of users mentioned in comments that are not watchers."""

  mention_set = get_mentioned_user_set(jira_client, issue)
  watcher_set = get_watcher_user_set(jira_client, issue)

  return mention_set.difference(watcher_set)


def add_mentions_to_watchers(jira_client, issue):
  """Add users mentioned in comments to watcher list"""

  logging.info("Adding watchers to %s", issue.key)
  for user in get_nonwatcher_mentions(jira_client, issue):
    logging.info("  %s", user)
    jira_client.add_watcher(issue, user)


def is_nominal_transition(nominal_flow, from_state, to_state):
  """
  Return true if the transition is forward in the nominal flow.
  """
  return to_state in nominal_flow.get(from_state, [])
