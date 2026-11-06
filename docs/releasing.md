# Versioning and Windows releases

This process preserves the three independent component versions:

- **API** also versions the Python distribution.
- **App** versions the shared browser/desktop frontend.
- **Desktop** versions the Windows wrapper.

The source of truth is [`_version.py`](../src/clue_engine/_version.py).
These versions do not change saved-game or HTTP schema versions. A release
identity includes all three components, even when only one changes:
`desktop-0.3.1-app-0.4.1-api-0.5.0`. Do not reuse a release tag or replace an
already published artifact. The numbers above are an example, not a promise
that this tuple has been released.

## Prepare a version

1. Start with a clean branch and run the development checks in the README.
2. Update only the components that changed. For example:

   ```powershell
   python -m tools.versioning set --app 0.4.2
   python -m tools.versioning check
   ```

   The command updates the source, the marked README section, and the latest
   unreleased changelog heading. If the previous entry is already dated, it
   starts a new empty unreleased section without altering the old one.
   Versions use three non-negative integers without leading zeroes. Review
   the changes and add accurate release notes under the new heading.
   An existing editable installation may retain old package metadata after an
   API version change; reinstall it with `python -m pip install -e ".[dev]"`
   when you need the local installed distribution metadata to match.
3. When ready, date the entry and check it:

   ```powershell
   python -m tools.versioning finalize --date 2026-11-06
   python -m tools.versioning check --release
   ```

   Use the actual release date. Commit the version, documentation, and notes
   together. Do not tag an unreleased or empty changelog entry.
4. Create an annotated tag matching the printed identity on that exact commit
   and push the commit and tag to GitHub. For example:

   ```powershell
   git tag -a desktop-0.3.1-app-0.4.2-api-0.5.0 -m "Clue Engine release"
   git push origin HEAD
   git push origin desktop-0.3.1-app-0.4.2-api-0.5.0
   ```

   The repository needs a GitHub remote and Actions enabled first. Configure
   Actions with permission to write repository contents. Review the tag and
   release notes before pushing; the tag starts the release workflow.

## What the workflow does

On a matching tag, the Windows x64 workflow checks out the tag, installs the
exact packages in [`release-requirements.txt`](../tools/release-requirements.txt)
under 64-bit CPython 3.13.3, and runs the full pytest and Ruff checks. Node.js
is mandatory for the JavaScript tests. The release builder rejects a dirty
checkout, a tag that differs from the component versions or points to another
commit, an undated changelog, missing dependencies, and unsupported platforms.
It also builds a Python wheel and verifies its API-version metadata and web
assets. The workflow does not publish that wheel. Since the distribution
version is the API version, publish a Python package only when the API version
has changed; an App- or Desktop-only release must not republish the same
Python distribution version.

It builds the one-file executable in a fresh temporary directory and runs its
packaged self-check. This checks the bundled desktop page and assets, displayed
versions, importing the window backend, and starting a game and submitting an
action. It **does not** open a WebView2 window or substitute for the GUI smoke
test below.

The workflow uploads a short-lived recovery artifact, then creates a **draft
GitHub Release** with:

- `ClueEngine-<tag>-windows-x64-portable.zip`, containing `ClueEngine.exe`
  and `release-manifest.json`;
- the archive's `.sha256` file; and
- the manifest separately, with the commit, versions, target, tool versions,
  executable hash, and runtime prerequisites.

The draft notes come from the dated changelog entry. Draft creation and asset
uploads are separate operations: if they fail partway through, inspect the
draft and the workflow's retained artifacts before recovering manually. Do not
silently replace an existing release or rerun over an existing artifact.

### Before publishing the draft

On a Windows x64 machine with the
[WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/)
and .NET Framework 4.6.2 or newer:

1. Download the draft archive and checksum, then compare the SHA-256 using
   `Get-FileHash -Algorithm SHA256 <archive>`. Confirm that the manifest
   identifies the intended tag and commit.
2. Extract the archive into a fresh directory, run `ClueEngine.exe`, and
   confirm all three displayed versions. Start a game, perform an action,
   change the theme, close the window, and reopen it to check that the theme
   persisted.
3. Check the release notes and assets, then publish the draft in GitHub.
   The executable is unsigned, so Windows may warn when it is downloaded.

This GUI step is intentionally manual: a successful automated self-check is
not evidence that WebView2 or a real desktop window works. The GitHub Release
is the durable archive for each published version; Actions artifacts expire.

## Build locally from a tag

Use 64-bit Windows, 64-bit CPython 3.13.3, Node.js 18 or newer, Git, and a
clean checkout at the tagged commit. A fresh virtual environment is strongly
recommended:

```powershell
python -m pip install -r tools/release-requirements.txt
python -m tools.release --tag desktop-0.3.1-app-0.4.2-api-0.5.0
```

The same checks and packaged self-check run locally. Files are created under
`dist\releases\<tag>`; an existing directory is never overwritten. The tool
does not upload or publish anything. The release requirements pin both direct
and transitive packages, but do not guarantee byte-for-byte reproducible builds
or authenticate downloaded packages with hashes. Update the pins deliberately
and validate a fresh build before releasing.

The ordinary development build described in the README remains available; it
is not a release artifact and does not provide these release guarantees.

## Existing historical builds

The pre-existing archives in the ignored `dist` directory are retained as
historical **unreleased** builds. Their filenames alone do not prove which
commit or dependencies produced them. Do not retroactively label them as
releases or delete them without reviewing their provenance.
