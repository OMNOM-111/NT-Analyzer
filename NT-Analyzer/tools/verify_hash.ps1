$src = "bridge\bin\Release\NTAnalyzerBridge.dll"
$dst = "C:\Users\dimon\Documents\NinjaTrader 8\bin\Custom\NTAnalyzerBridge.dll"

$srcFile = Get-Item $src
$dstFile = Get-Item $dst

Write-Host "Source DLL: $($srcFile.FullName)"
Write-Host "Source Size: $($srcFile.Length) bytes"
Write-Host "Source Modified: $($srcFile.LastWriteTime)"
$srcHash = (Get-FileHash -Path $src -Algorithm SHA256).Hash
Write-Host "Source SHA-256: $srcHash"

Write-Host ""
Write-Host "Deployed DLL: $($dstFile.FullName)"
Write-Host "Deployed Size: $($dstFile.Length) bytes"
Write-Host "Deployed Modified: $($dstFile.LastWriteTime)"
$dstHash = (Get-FileHash -Path $dst -Algorithm SHA256).Hash
Write-Host "Deployed SHA-256: $dstHash"

Write-Host ""
if ($srcHash -eq $dstHash) {
    Write-Host "CONFIRMED: SHA-256 hashes match."
} else {
    Write-Host "WARNING: SHA-256 hashes do NOT match."
}
