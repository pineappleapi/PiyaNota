$stdin = [Console]::In.ReadToEnd()
$payload = $stdin | ConvertFrom-Json
$path = $payload.tool_input.file_path
if ($path -and ($path -match 'docs[\\/]bug-tracker\.md$')) {
    Import-Module BurntToast
    New-BurntToastNotification -Text 'Claude Code', 'Bug logged in bug-tracker.md'
}
