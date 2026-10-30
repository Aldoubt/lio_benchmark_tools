# Synthetic bag regression

Synthetic message sequences, not real flight bags or a ROS/DDS runtime test.
Known mutations are generator facts. Observed events do not establish real-world causes or drift accuracy.

| Case | Known injected change | Tool observations (nonzero) | Regression |
|---|---|---|---|
| normal | None | No threshold events | PASS |
| header_backtrack | Subtract 0.4 s from headers at original indices 20..79; record clock unchanged. | header_backtracks=1, high_offsets=60 | PASS |
| recorded_backtrack | Subtract 0.3 s from record timestamp at index 20; preserve fixture reader order. | recorded_backtracks=1, negative_offsets=1 | PASS |
| duplicate_header | Copy header 19 to header 20; retain both records. | header_duplicates=1 | PASS |
| dropout | Remove original indices 20..29 (10 messages); remaining timestamps unchanged. | header_gaps=1, recorded_gaps=1 | PASS |
| delay_step | Add 0.35 s to record timestamps at indices 20..79, simulating delayed recording. | high_offsets=60 | PASS |
| constant_delay | Add 0.35 s to all record times: designated synthetic buffering delay. | high_offsets=80 | PASS |
| clock_offset | Add 0.35 s to all record times: designated clock offset; observationally identical to constant_delay. | high_offsets=80 | PASS |
| negative_offset | Add 10 s to all header timestamps: distinct clock domains. | negative_offsets=80 | PASS |
| position_jump | Add 2 m to x at original indices 40..79. | position_jumps=1 | PASS |
| yaw_jump | Apply a 90 degree yaw step at original indices 40..79. | yaw_jumps=1, rotation_jumps=1 | PASS |
| roll_jump | Apply a 60 degree roll_jump at original indices 40..79; yaw unchanged. | rotation_jumps=1 | PASS |
| pitch_jump | Apply a 60 degree pitch_jump at original indices 40..79; yaw unchanged. | rotation_jumps=1 | PASS |
| quaternion_sign | Negate all quaternion components at indices 40..79; same physical orientation. | No threshold events | PASS |
| combined | Remove indices 20..29; subtract 0.4 s from headers at original 40..79; add 2 m x at original 50..79. | header_backtracks=1, header_gaps=1, recorded_gaps=1, high_offsets=40, position_jumps=1 | PASS |

All proposed causes remain UNCONFIRMED_BY_TOOL. Constant delay and clock offset intentionally produce identical observations.
Dropout only proves an observed inter-record gap; its exact removed count is known solely from the injection manifest.
Position/rotation steps are diagnostics; relocalization or loop correction may legitimately produce them.
Each case contains input.json, injection.json, audit.json and audit.md. Outputs refuse directory reuse.
