# ---------------------------
# XBOS Login Test Script
# ---------------------------

# API endpoint
$Url = "http://127.0.0.1:8000/kernel/auth/login"

# Headers for multi-tenant XBOS
$Headers = @{
    "x-tenant-code" = "CM001"
    "x-branch-code" = "BR001"
    "Content-Type"  = "application/json"
}

# Login payload
$Body = @{
    "username" = "cashier"
    "password" = "password"
} | ConvertTo-Json

Write-Host "=> Sending login request..." -ForegroundColor Cyan

$response = Invoke-RestMethod `
    -Method POST `
    -Uri $Url `
    -Headers $Headers `
    -Body $Body

Write-Host "`n=> Login Response:" -ForegroundColor Green
$response | Format-List

# Extract the token
$Token = $response.access_token

Write-Host "`n=> Access Token Issued by API:" -ForegroundColor Yellow
Write-Host $Token

# ---------------------------
# OPTIONAL: Decode the token header/payload WITHOUT verifying signature
# ---------------------------

function Decode-JWTPart($EncodedPart) {
    $remainder = $EncodedPart.Length % 4
    if ($remainder -ne 0) {
        $EncodedPart += "=" * (4 - $remainder)
    }
    $Bytes = [Convert]::FromBase64String($EncodedPart.Replace("-", "+").Replace("_", "/"))
    return [System.Text.Encoding]::UTF8.GetString($Bytes)
}

$Parts = $Token.Split(".")

Write-Host "`n=> JWT Header:" -ForegroundColor Cyan
Decode-JWTPart $Parts[0]

Write-Host "`n=> JWT Payload:" -ForegroundColor Cyan
Decode-JWTPart $Parts[1]

Write-Host "`n=> Use this header/payload to confirm the backend secret." -ForegroundColor DarkGray
