# Copyright 2019 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Static implementation of tasks. Does not directly execute them."""

from clusterfuzz._internal.bot.tasks import blame_task
from clusterfuzz._internal.bot.tasks import impact_task
from clusterfuzz._internal.bot.tasks import symbolize_task
from clusterfuzz._internal.bot.tasks import unpack_task
from clusterfuzz._internal.bot.tasks import upload_reports_task
from clusterfuzz._internal.bot.tasks import utasks
from clusterfuzz._internal.bot.tasks.utasks import analyze_task
from clusterfuzz._internal.bot.tasks.utasks import corpus_pruning_task
from clusterfuzz._internal.bot.tasks.utasks import fuzz_task
from clusterfuzz._internal.bot.tasks.utasks import minimize_task
from clusterfuzz._internal.bot.tasks.utasks import progression_task
from clusterfuzz._internal.bot.tasks.utasks import regression_task
from clusterfuzz._internal.bot.tasks.utasks import variant_task
from clusterfuzz._internal.metrics import logs


class BaseTask:
  """Base module for tasks."""

  def __init__(self, module):
    self.module = module

  def execute(self, task_argument, job_type, uworker_env):
    """Executes a task."""
    raise NotImplementedError('Child class must implement.')


class TrustedTask(BaseTask):
  """Implementation of a task that is run on a single machine. These tasks were
  the original ones in ClusterFuzz."""

  def execute(self, task_argument, job_type, uworker_env):
    # Simple tasks can just use the environment they don't need the uworker env.
    del uworker_env
    self.module.execute_task(task_argument, job_type)


def utask_factory(task_module, in_memory=True):
  """Returns a task implemention for a utask. Depending on the global
  configuration, the implementation will either execute the utask entirely on
  one machine or on multiple."""
  if in_memory:
    logs.log('Using memory for utasks.')
    return UTaskLocalExecutor(task_module)

  logs.log('Using GCS for utasks.')
  return UTask(task_module)


class UTask(BaseTask):
  """Represents an untrusted task. Executes the preprocess part on this machine
  and causes the other parts to be executed on on other machines."""

  def execute(self, task_argument, job_type, uworker_env):
    """Executes a utask locally."""
    preprocess_result = utasks.tworker_preprocess(self.module, task_argument,
                                                  job_type, uworker_env)

    if preprocess_result is None:
      return

    # TODO(metzman): Execute main on other machines.


class UTask(BaseTask):
  """Represents an untrusted task. Executes the preprocess and main parts on
  this machine and causes postprocess to be executed on on other machines."""

  def execute(self, task_argument, job_type, uworker_env):
    """Executes a utask locally."""
    preprocess_result = utasks.tworker_preprocess(self.module, task_argument,
                                                  job_type, uworker_env)

    if preprocess_result is None:
      return

    input_download_url, _ = preprocess_result
    utasks.uworker_main(input_download_url)
    logs.log('Utask: done with preprocess and main.')


class UTaskLocalExecutor(BaseTask):
  """Represents an untrusted task. Executes it entirely locally and in
  memory."""

  def execute(self, task_argument, job_type, uworker_env):
    """Executes a utask locally in-memory."""
    uworker_input = utasks.tworker_preprocess_no_io(self.module, task_argument,
                                                    job_type, uworker_env)
    if uworker_input is None:
      return
    uworker_output = utasks.uworker_main_no_io(self.module, uworker_input)
    if uworker_output is None:
      return
    utasks.tworker_postprocess_no_io(self.module, uworker_output, uworker_input)
    logs.log('Utask local: done.')


class PostprocessTask(BaseTask):
  """Represents postprocessing of an untrusted task."""

  def __init__(self, module='none'):
    # We don't need a module, postprocess isn't a real task, it's one part of
    # many different tasks.
    super().__init__(module)

  def execute(self, task_argument, job_type, uworker_env):
    """Executes postprocessing of a utask."""
    # These values are None for now.
    del job_type
    del uworker_env
    input_path = task_argument
    utasks.tworker_postprocess(input_path)


class UworkerMainTask(BaseTask):
  """Represents uworker main of an untrusted task. This should only be used for
  tasks that cannot use Google Cloud batch (e.g. Mac)."""

  # TODO(metzman): Merge with PostprocessTask.
  def __init__(self, module='none'):
    # We don't need a module, uworker_main isn't a real task, it's one part of
    # many different tasks.
    super().__init__(module)

  def execute(self, task_argument, job_type, uworker_env):
    """Executes uworker_main of a utask."""
    # These values are None for now.
    del job_type
    del uworker_env
    input_path = task_argument
    utasks.uworker_main(input_path)


COMMAND_MAP = {
    # TODO(metzman): Change analyze task away from in-memory.
    'analyze': utask_factory(analyze_task),
    'blame': TrustedTask(blame_task),
    'corpus_pruning': utask_factory(corpus_pruning_task),
    'fuzz': utask_factory(fuzz_task),
    'impact': TrustedTask(impact_task),
    'minimize': utask_factory(minimize_task),
    'progression': utask_factory(progression_task),
    'regression': utask_factory(regression_task),
    'symbolize': TrustedTask(symbolize_task),
    'unpack': TrustedTask(unpack_task),
    'uworker_postprocess': PostprocessTask(),
    'upload_reports': TrustedTask(upload_reports_task),
    'uworker_main': UworkerMainTask(),
    'variant': utask_factory(variant_task),
}


def is_multimachine_executed(task_name):
  """Returns True if |task_name| is executed on multiple machine. This does not
  include utasks that are using the in-memory executor."""
  task = COMMAND_MAP[task_name]
  return isinstance(task, UTask)


def get_multimachine_tasks():
  """Returns all tasks that are not executed on one machine. This does not
  include utasks that are using the in memory executor."""
  return [
      task_name for task_name in COMMAND_MAP
      if is_multimachine_executed(task_name)
  ]
