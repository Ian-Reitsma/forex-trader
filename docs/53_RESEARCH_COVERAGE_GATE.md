# Research coverage gate

This test-only tranche restores repository-wide coverage after adding the v0.7.28 exact managed and adaptive historical research modules. It does not change strategy parameters, historical data, execution assumptions, or validation windows.

The added tests exercise invalid managed-target contracts, long/short exact tick outcomes, timeout behavior, insufficient-history behavior, negative-edge selection rejection, frozen managed evaluation, adaptive value-object validation, causal evaluation-boundary checks, instrument/direction cohort filtering, unstable-history rejection, and frozen adaptive evaluation after shadow warmup.

The repository coverage threshold remains unchanged. The purpose of this tranche is to meet the existing threshold through meaningful behavioral coverage rather than lowering the gate or excluding the new research modules.
