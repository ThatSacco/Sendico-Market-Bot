# Central limits update v6

This update removes duplicated operational caps from `config.yaml` and introduces `data/run_limits.yaml` as their sole editable source.

The loader validates the central file and maps its friendly sections into the existing nested runtime keys, so the rest of the scanner does not need to change. One detailed-analysis value now supplies both the Tier 2 and global vision limits.

The configuration tests validate relationships rather than fixed values. Increasing `screening.max_listings_per_run` from 40 to 100, for example, no longer requires changing Python tests.
