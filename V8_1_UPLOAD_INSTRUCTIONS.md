# GitHub-only v8.1 repair and cleanup

The v8 files were uploaded, but GitHub does not delete files that are absent from an upload. The old tests and legacy Python modules therefore remained and pytest attempted to load both architectures.

## Upload

Upload every file from this package into the repository, preserving paths. This re-adds any missing v8 test files and adds:

`.github/workflows/v8-cleanup.yml`

Do not delete files manually before running the workflow.

## Run the cleanup

1. Open **Actions**.
2. Select **Finalize v8 Cleanup**.
3. Select **Run workflow** on the `main` branch.
4. Wait for the workflow to finish.

The workflow verifies the full v8 file set, removes old tests/modules/docs, runs the v8 test suite, commits the deletions, and then removes itself.

After it succeeds, run **Test Sendico Market Bot**, followed by a manual **Scan Sendico Pokemon Deals** run.
