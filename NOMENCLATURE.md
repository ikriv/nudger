# Nomenclature

This document defines the experimental terms used by the code, database, CLI,
reports, and documentation.

## Demo

A **demo** is a task family. The allowed values are:

- `refund`
- `columns`

## Demo variant

A **demo variant** is a named fixture within a demo. Its name includes the demo
prefix so it remains meaningful when viewed by itself.

Current variants are:

- `refund_flirt`
- `refund_damaged`
- `refund_missing`
- `refund_small`
- `refund_expired`
- `columns_random`
- `columns_artists`

The term *case* is not used for a demo variant. The term *names* is not used for
the columns fixture.

## Scenario

A **scenario** is the complete set of model-independent experimental inputs. It
includes the demo variant, question-prompt variant, nudger, execution limits, and
any other input that can affect model behavior.

A scenario does not include the model or anything observed after execution.

A **demo session** is the mutable runtime state created from a scenario for one
attempt. It is discarded before a retry. The term *scenario* is not used for this
mutable state.

## Run

A **run** evaluates one scenario against one model using a scheduled number of
samples. A run never combines multiple models or multiple scenarios.

Run completeness is derived: a run is complete when its number of recorded
samples equals `num_samples_scheduled`. There is no separate lifecycle flag.

The model's requested name and settings belong to the run. The model name actually
served by an API may be recorded on each sample.

## Sample

A **sample** is one independent execution within a run. `--samples 5` schedules five
samples for that run.

`sample_number` is the one-based ordinal of a sample within its run. The term
*repetition index* is not used.

Each sample records:

- `sample_status`: whether it was evaluated or ended with an infrastructure error;
- `outcome`: the observed behavioral ending, such as `completed`, `stalled`, or
  `call_limit`, when the sample was evaluated;
- measurements, grade, transcript, usage, and any final error;
- `num_retries`.

Infrastructure-error samples remain recorded but do not enter behavioral-rate
denominators.

A sample's audit and cost include every attempt made for that sample. A retry
does not replace or discard earlier attempt data.

## Retry

A **retry** is the evaluator re-executing the same sample after a transient
infrastructure failure. A retry does not create another sample or another run.

The provider SDKs have automatic retries disabled. Therefore *provider retry* is
not used: the evaluator performs the retry. If retries are exhausted, the sample
ends with an infrastructure-error status.

## Batch

A **batch** is the optional operational grouping for the runs started by one CLI
invocation. It can carry invocation time, software versions, and an operator note.
It is not an experimental unit and does not contain model, demo, or scenario
lists; those are derived from its runs.

The term *run family* is not used.

## Terms not used

Avoid these ambiguous terms in public interfaces and database columns:

- `case`
- `names`
- `condition`
- `repetition_index`
- `provider_retry`
- `run_family`
