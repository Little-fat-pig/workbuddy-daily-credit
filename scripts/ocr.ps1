param([string]$ImagePath, [string]$OutFile, [switch]$ListLangs)

# Windows built-in OCR (Windows.Media.Ocr) helper.
# Writes a UTF-8 JSON array of words with bounding boxes (image pixel coords).

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Foundation, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Foundation, ContentType=WindowsRuntime]

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await($op, $type) {
    $m = $asTaskGeneric.MakeGenericMethod($type)
    $t = $m.Invoke($null, @($op))
    $t.Wait(-1) | Out-Null
    $t.Result
}

$langs = [Windows.Media.Ocr.OcrEngine]::AvailableRecognizerLanguages
if ($ListLangs) {
    ($langs | ForEach-Object { $_.LanguageTag }) -join ','
    exit 0
}

$engine = $null
foreach ($tag in @('zh-Hans-CN', 'zh-Hans', 'zh-CN')) {
    try {
        $lang = New-Object Windows.Globalization.Language $tag
        if ([Windows.Media.Ocr.OcrEngine]::IsLanguageSupported($lang)) {
            $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
            if ($null -ne $engine) { break }
        }
    } catch { }
}
if ($null -eq $engine) { $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages() }

$json = '{"error":"NO_ENGINE"}'
if ($null -ne $engine) {
    $full = (Resolve-Path $ImagePath).Path
    $file = Await ([Windows.Storage.StorageFile]::GetFileFromPathAsync($full)) ([Windows.Storage.StorageFile])
    $stream = Await ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $result = Await ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $out = New-Object System.Collections.ArrayList
    foreach ($line in $result.Lines) {
        foreach ($w in $line.Words) {
            $r = $w.BoundingRect
            $null = $out.Add([pscustomobject]@{
                text = $w.Text
                x = [int]$r.X; y = [int]$r.Y; w = [int]$r.Width; h = [int]$r.Height
            })
        }
    }
    $json = ConvertTo-Json -InputObject @($out) -Compress -Depth 4
}

if ($OutFile) {
    [System.IO.File]::WriteAllText($OutFile, $json, (New-Object System.Text.UTF8Encoding($false)))
} else {
    [Console]::Out.Write($json)
}
