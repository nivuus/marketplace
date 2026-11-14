"""Application ids every boundary must reject: traversal, absolute paths,
separators, control characters, and anything that is not a lowercase slug."""

BAD_APP_IDS = ["", "..", ".", "/abs", "/", "a/b", "a\\b", "../x", "x\n", "Demo", "-x", " x"]
