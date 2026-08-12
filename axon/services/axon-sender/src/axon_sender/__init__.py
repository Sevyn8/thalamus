"""Axon's sender: the poll loop over ``axon-send-requested``.

WHY THIS IS A SERVICE AND NOT A JOB, which is the one shape decision the rest follows from. The
nearer precedent is DIS's streaming-consumer, a Cloud Run SERVICE at min_instances=1 holding a
subscription, and not Synapse's orchestrator, which is a scheduled JOB. A sender has no cadence.
It has a queue, and a queue is drained continuously or it is a backlog.

WHAT IT DOES, IN ONE LOOP PASS: pull, parse the envelope, hand the message to the adapter, append
the outcome to the ledger, ack. Every piece of that behaviour is ``thalamus-axon``'s; this
package is the loop, the configuration and the health surface around it.

WHAT IT DELIBERATELY IS NOT. It publishes nothing, so it holds no publisher grant and no topic.
It reads nothing, so it connects as ``axon_sender``, which holds INSERT on one table and no
SELECT anywhere. It serves no route but ``/healthz``, so it carries no invoker binding at all.
"""
