# User-invoked session setup only; Python production code reads the environment.
$ErrorActionPreference = 'Stop'
$deepseekSecureValue = Read-Host 'Paste your DeepSeek API key (hidden), then press Enter' -AsSecureString
$deepseekBstr = [IntPtr]::Zero
try {
    $deepseekBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($deepseekSecureValue)
    $env:DEEPSEEK_API_KEY = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($deepseekBstr)
    if ([string]::IsNullOrWhiteSpace($env:DEEPSEEK_API_KEY)) {
        Remove-Item Env:DEEPSEEK_API_KEY -ErrorAction SilentlyContinue
        throw 'Empty key. The environment variable was not retained.'
    }
    Write-Output 'DEEPSEEK_API_KEY is set for this PowerShell session. The value was not displayed or saved to a file.'
} finally {
    if ($deepseekBstr -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($deepseekBstr)
    }
    $deepseekSecureValue.Dispose()
}
