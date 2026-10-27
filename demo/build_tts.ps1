$ErrorActionPreference = "Stop"
$root = "E:\SELF\skills\soundcheck\demo"
New-Item -ItemType Directory -Force -Path $root | Out-Null
Add-Type -AssemblyName System.Speech

$lines = @(
  @{ voice = "Microsoft Huihui";   rate = 0;  text = "你终于来了。" },
  @{ voice = "Microsoft Kangkang"; rate = -1; text = "三年了，你一点都没变。" },
  @{ voice = "Microsoft Huihui";   rate = 1;  text = "有些事，变了就是变了。" },
  @{ voice = "Microsoft Kangkang"; rate = 0;  text = "那这个孩子……" },
  @{ voice = "Microsoft Huihui";   rate = -2; text = "他不是你的。" },
  @{ voice = "Microsoft Kangkang"; rate = 2;  text = "你说什么？" }
)
$i = 0
foreach ($l in $lines) {
  $s = New-Object System.Speech.Synthesis.SpeechSynthesizer
  $s.SelectVoice($l.voice)
  $s.Rate = $l.rate
  $s.Volume = 100
  $p = Join-Path $root ("line_{0}.wav" -f $i)
  $s.SetOutputToWaveFile($p)
  $s.Speak($l.text)
  $s.Dispose()
  $i++
}
Get-ChildItem $root -Filter "line_*.wav" | Select-Object Name, @{n='kb';e={[math]::Round($_.Length/1kb,1)}} | Format-Table -AutoSize | Out-String -Width 60
$one = Get-ChildItem $root -Filter "line_0.wav"
Write-Output ("format: {0} Hz, {1} ch, {2} bit" -f ([math]::Round($one.Length)), 0, 0)
