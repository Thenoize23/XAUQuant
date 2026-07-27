' Launch the CENT supervisor with NO visible window (runs in the background).
' Reliability: the supervisor loop restarts the runner if it ever dies.
CreateObject("Wscript.Shell").Run "cmd /c ""C:\Users\conoi\XAUQuant\mcp\run_cent_supervisor.bat""", 0, False
