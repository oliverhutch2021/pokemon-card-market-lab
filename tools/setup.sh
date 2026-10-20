#!/bin/sh
# Run once after cloning: turns on the publish guard and sets a private author email.
# Optional: path to the private denylist (kept in the private data repo).
git config core.hooksPath .githooks
git config user.name "Oliver Hutchinson"
git config user.email "310228121+oliverhutch2021@users.noreply.github.com"
[ -n "$1" ] && git config guard.denylist "$1"
echo "guard hooks on; author email set to GitHub noreply"
