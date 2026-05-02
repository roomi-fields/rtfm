# RTFM demo — generates rtfm-demo.gif
# Run: vhs docs/demo/rtfm-demo.tape

Output docs/demo/rtfm-demo.gif

Require rtfm

Set FontSize 18
Set Width 1400
Set Height 620
Set Padding 24
Set TypingSpeed 35ms
Set Theme "Catppuccin Mocha"

# Setup: cd to project so RTFM auto-detects the .rtfm DB
Hide
Type "cd /home/romi/dev/mcp/RTFM && clear"
Enter
Sleep 500ms
Show

# Identity line
Type "# RTFM — open retrieval layer for AI agents"
Sleep 1.5s
Enter
Sleep 400ms

# Show scale
Type "rtfm stats"
Sleep 300ms
Enter
Sleep 1.8s

# One query → many file types
Type "rtfm search 'incremental sync hash tracking' --limit 4 --corpus default"
Sleep 300ms
Enter
Sleep 3s

# Tagline
Type "# code · docs · tests · context — one query, surgical results"
Sleep 1.2s
Enter
Type "# free · local · MIT — pip install rtfm-ai"
Sleep 4s
