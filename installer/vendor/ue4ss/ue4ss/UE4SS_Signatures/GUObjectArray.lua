-- PBZ build 26367565 / CL-302256_JKS-17280.
-- Validated by read-only inspection of the running object array and name pool.
-- Resolve the RIP-relative operand; do not return a hardcoded process address.
function Register()
    return "48 8B 05 72 C6 95 0C"
end

function OnMatchFound(MatchAddress)
    local Offset = DerefToInt32(MatchAddress + 3)
    return MatchAddress + 7 + Offset - 0x18
end
