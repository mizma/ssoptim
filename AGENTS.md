# SSOptim project

## Project Overview

* Python based cli application
* Environment management: `uv`
* Testing: `pytest`

## Code Structure

* See [DESIGN.md][1] for detailed project structure and requirements.
* See [README.md][2] for user facing contracts.

## Workflow

### Common workflow requirements during code change

* When running the python code, use `uv` to setup virtual environment and install
  dependencies (Refer to [Makefile](./Makefile), or [tasks.py](./tasks.py)).
* If any changes are made to the code, run tests and verify that the results
  of the tests matches expectation of current implementation state.
  (could be a expected fail state if the implementation status is only scaffolding etc.)
* For long running tasks, split into small steps.
* If milestones are defined, commit changes before moving onto the next milestone
* Do not touch the [CHANGES.md](./CHANGES.md) file until a release is planned.
  * [CHANGES.md](./CHANGES.md) will be edited just before release based on the commit history available
    at the time of release to avoid any premature change history.

### Workflow Requirements for Feature addition/change implementation tasks

* Always update [DESIGN.md][1] and [README.md][2] before **AND** after implementation when there is
  a requirement/feature change.
  * Update documentation to clarify what the plan is for the implementation before implementation.
  * Update documentation to match implementation details after the implementation
    phase so any implementation limitations are documented.
* Always implement or update tests that relates to the change before running tests.
* After implementation and test, always re-verify the implementation changes against
  the documentation in [DESIGN.md][1] and [README.md][2] and verify integrity.
  * If there are any conflicting state between the documentation and implementation,
    always report the conflicts after implementation and tests are done, and ask how they should be resolved.

### Commit rule

* Always

## Boundaries

* Only commit code to the current working branch unless otherwise instructed.
* For temporary workspace, use `/tmp/*` to put any temporary testing code, scaffolding etc.
  * make sure you make a subdirectory under `/tmp/` that is unique to avoid conflicts
    with other tasks.

[1]: ./DESIGN.md
[2]: ./README.md
