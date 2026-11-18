# The btrc-job scheduled task: run C:\btrc\job\command.ps1 in the logged-on desktop session.
# The host writes the command, starts the task, follows output.log and reads the status from exit.
$job = 'C:\btrc\job'
Remove-Item "$job\exit" -ErrorAction SilentlyContinue
$status = 1
try {
    & powershell -NoProfile -ExecutionPolicy Bypass -File "$job\command.ps1" *> "$job\output.log"
    $status = $LASTEXITCODE
} catch {
    Add-Content "$job\output.log" $_
}
Set-Content "$job\exit" $status
