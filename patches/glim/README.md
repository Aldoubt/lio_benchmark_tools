# GLIM dependency patches

## `gtsam_points_v1.2.2_boost_none.patch`

- Target repository: `https://github.com/koide3/gtsam_points.git`
- Target tag/commit: `v1.2.2` / `9d32e7dbecf6015560d84b4901d6b0a6f483ec46`
- Reason: Boost 1.74's `boost::none_t` is not a literal type, so GCC 11 rejects
  the upstream `constexpr auto NoneValue = boost::none` declaration.
- Modified file: `include/gtsam_points/util/gtsam_migration.hpp`
- Behavior change: none; the namespace-level sentinel remains immutable and the
  C++17 inline variable keeps one definition across translation units.
- Risk: minimal; initialization changes from constant initialization to static
  initialization before use.
- Verification: rebuild `gtsam_points` in Release mode, then build GLIM v1.2.2.
- Rollback: run `git apply -R <patch>` in the `gtsam_points` checkout or recreate
  the pinned clean checkout.
