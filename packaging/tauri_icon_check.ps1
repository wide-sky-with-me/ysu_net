# Cloud-only PE resource icon acceptance; never launches the application/installer.
$ErrorActionPreference = 'Stop'
if ($env:GITHUB_ACTIONS -ne 'true' -or $env:RUNNER_OS -ne 'Windows') {
  throw 'Executable icon acceptance runs only on Windows GitHub Actions'
}
Add-Type -AssemblyName System.Drawing
$root = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..'))
$output = Join-Path $root 'dist\rust-desktop-icons'
[IO.Directory]::CreateDirectory($output) | Out-Null
$source = Join-Path $root 'desktop\src-tauri\icons\icon.ico'
$app = Join-Path $root 'desktop\src-tauri\target\release\ysu-net.exe'
$setups = @(Get-ChildItem -LiteralPath (Join-Path $root 'desktop\src-tauri\target\release\bundle\nsis') -Filter '*-setup.exe' -File)
if ($setups.Count -ne 1) { throw 'Expected exactly one NSIS installer for icon acceptance' }
function Save-IconPixels($Icon, [string]$Name) {
  $bitmap = New-Object Drawing.Bitmap(32, 32)
  $graphics = [Drawing.Graphics]::FromImage($bitmap)
  try {
    $graphics.Clear([Drawing.Color]::White)
    $graphics.DrawIcon($Icon, (New-Object Drawing.Rectangle(0, 0, 32, 32)))
    $bitmap.Save((Join-Path $output ($Name + '.png')), [Drawing.Imaging.ImageFormat]::Png)
    $pixels = New-Object byte[] (32 * 32 * 4)
    for ($y = 0; $y -lt 32; $y++) {
      for ($x = 0; $x -lt 32; $x++) {
        $bytes = [BitConverter]::GetBytes($bitmap.GetPixel($x, $y).ToArgb())
        [Array]::Copy($bytes, 0, $pixels, ($y * 32 + $x) * 4, 4)
      }
    }
    $sha = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($sha.ComputeHash($pixels))).Replace('-', '').ToLowerInvariant() }
    finally { $sha.Dispose() }
  } finally { $graphics.Dispose(); $bitmap.Dispose(); $Icon.Dispose() }
}
$expectedIcon = New-Object Drawing.Icon($source, (New-Object Drawing.Size(32, 32)))
$expected = Save-IconPixels $expectedIcon 'source-icon'
$records = @()
foreach ($entry in @(@{Name='application-icon'; Path=$app}, @{Name='installer-icon'; Path=$setups[0].FullName})) {
  $icon = [Drawing.Icon]::ExtractAssociatedIcon($entry.Path)
  if ($null -eq $icon) { throw 'Executable has no associated icon' }
  $actual = Save-IconPixels $icon $entry.Name
  if ($actual -ne $expected) { throw ('Embedded executable icon differs from generated ICO: ' + $entry.Name) }
  $records += @{kind=$entry.Name; pixelSha256=$actual; matchesGeneratedIcon=$true}
}
@{ok=$true; sourcePixelSha256=$expected; executables=$records; payloadExecuted=$false} |
  ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $output 'windows-icons.json') -Encoding utf8
Write-Output 'Application and NSIS installer embedded icons match the generated ICO.'
