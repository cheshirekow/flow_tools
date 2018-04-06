import os
import re
import subprocess
import textwrap

import git

class Configuration(object):
  def __init__(self, release_pattern=None, release_key=None):
    self.release_pattern = release_pattern
    self.release_key = release_key

def resolve_merge_commit(commit):
  """
  If commit was made by merge-queue, find the real owner and return that
  commit.
  """
  try:
    while commit.author.email.startswith(u'merge'):
      commit = commit.parents[-1]
    return commit
  except:  # pylint:disable=bare-except
    return None


def get_merge_commits(repo_path, branch='master'):
  """
  Return a generator yielding commits into master.
  """
  repo = git.Repo(repo_path)

  # NOTE(josh): usually we would want --merges, but since skydio has a dumb
  # merge strategy we have to do this nonsense.
  git_proc = subprocess.Popen(['git', 'log', '--no-merges', '--first-parent',
                               '--format=%H', branch],
                              cwd=repo_path,
                              stdout=subprocess.PIPE)

  for commit_hash in git_proc.stdout:
    commit = repo.commit(commit_hash.strip())

    if commit is not None:
      yield commit

  git_proc.stdout.close()
  git_proc.wait()



def get_merges_that_close_issues(tag_map, repo_path, branch='master'):
  """
  Return a generator yielding pairs (commit, resolutions) where commit is the
  commit object from git python and resolutions is a map from issue key to
  resolution from the commit message (i.e. "resolved", "closed")
  """

  for commit in get_merge_commits(repo_path, branch):
    resolutions = {}
    for line in commit.message.splitlines():
      parts = line.strip().split(':', 1)
      if len(parts) != 2:
        continue
      key, issues = parts

      resolution = tag_map.get(key, None)
      if resolution is None:
        resolution = tag_map.get(key.lower(), None)
        if resolution is None:
          continue

      for issue in issues.split(','):
        issue = issue.strip()
        if issue is None or issue == 'None':
          continue
        resolutions[issue.strip()] = resolution

    if resolutions:
      yield commit, resolutions



def get_releases(repo_path, config):
  """
  Parse all tags in `repo_path` looking for version strings that match the
  pattern in the config file. Return them in sorted order using the key
  function from the config file.
  """

  version_re = re.compile(config.git.release_pattern)
  versions = []
  proc = subprocess.Popen(['git', '--git-dir', os.path.join(repo_path, '.git'),
                           'tag'], stdout=subprocess.PIPE)

  with proc.stdout:
    for line in proc.stdout:
      line = line.strip()
      if version_re.match(line):
        versions.append(line)

  proc.wait()
  return sorted(versions, key=config.git.release_key)


def get_merges_in_series(repo_path, from_commit, to_commit):
  """
  Return a generator over merge commits in the sequence from_commit..to_commit
  """

  # NOTE(josh): usually we would want --merges, but since skydio has a dumb
  # merge strategy we have to do this nonsense.
  git_proc = subprocess.Popen(
      ['git', '--git-dir', os.path.join(repo_path, '.git'),
       'log', '--no-merges', '--first-parent', '--format=%H',
       '{}...{}'.format(from_commit, to_commit)],
      stdout=subprocess.PIPE)

  with git_proc.stdout:
    for commit_hash in git_proc.stdout:
      commit_hash = commit_hash.strip()
      yield commit_hash

  git_proc.wait()
  assert git_proc.returncode == 0, \
    "Failed to log {}...{}".format(from_commit, to_commit)


def get_resolutions(repo_path, commit, tag_map):
  """
  Return a dictionary of {issue-key : resolution} for issues closed in this
  commit
  """

  message = subprocess.check_output(
      ['git', '--git-dir', os.path.join(repo_path, '.git'),
       'log', '--format=%B', '-n', '1', commit])

  resolutions = {}
  for line in message.splitlines():
    parts = line.strip().split(':', 1)
    if len(parts) != 2:
      continue
    key, issues = parts

    resolution = tag_map.get(key, None)
    if resolution is None:
      resolution = tag_map.get(key.lower(), None)
      if resolution is None:
        continue

    for issue in issues.split(','):
      issue = issue.strip()
      if issue is None or issue == 'None':
        continue
      resolutions[issue] = resolution

  return resolutions

def get_message_summary(repo_path, commit, maxlen=70):
  """
  Return the first line of the commit message
  """
  wrapper = textwrap.TextWrapper(width=maxlen, initial_indent='',
                                 subsequent_indent=' '*10)
  summary = subprocess.check_output(
      ['git', '--git-dir', os.path.join(repo_path, '.git'),
       'log', '--format=%s', '-n', '1', commit]).strip()
  return '{}: {}'.format(commit[:8], wrapper.fill(summary))

def get_release_notes(repo_path, from_tag, to_tag):
  """
  Return a list of commit message summaries closed between two consecutive
  versions
  """

  merge_base = subprocess.check_output(['git', '--git-dir',
                                        os.path.join(repo_path, '.git'),
                                        'merge-base', from_tag, to_tag]).strip()

  summaries = []
  for commit in get_merges_in_series(repo_path, merge_base, to_tag):
    summaries.append(get_message_summary(repo_path, commit))

  return summaries

def get_issues_closed_in_series(repo_path, from_tag, to_tag, tag_map):
  """
  Return a list of issues that were closed between two consecutive versions
  identified with a git tag
  """
  merge_base = subprocess.check_output(['git', '--git-dir',
                                        os.path.join(repo_path, '.git'),
                                        'merge-base', from_tag, to_tag]).strip()
  resolved_issues = []
  for commit in get_merges_in_series(repo_path, merge_base, to_tag):
    resolutions = get_resolutions(repo_path, commit, tag_map)
    resolved_issues.extend(resolutions.keys())

  return sorted(resolved_issues)
