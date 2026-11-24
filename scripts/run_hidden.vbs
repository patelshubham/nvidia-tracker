' Starts the NVDA watcher with no visible window. Used by the scheduled task because launching the
' venv's pythonw.exe directly from Task Scheduler fails with 0xC0000142 on this machine.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
root = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
sh.CurrentDirectory = root
sh.Environment("Process")("NVDA_HEADLESS") = "1"
sh.Run """" & root & "\.venv\Scripts\python.exe"" -m nvda_tracker watch", 0, False
