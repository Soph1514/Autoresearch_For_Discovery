"""Model-synthesised fitness functions, used only where the Lean compiler cannot reach.

A synthesised scorer is untrusted code. It is never imported or executed on the
host; it runs in the candidate worker container exactly like a candidate program.
"""
