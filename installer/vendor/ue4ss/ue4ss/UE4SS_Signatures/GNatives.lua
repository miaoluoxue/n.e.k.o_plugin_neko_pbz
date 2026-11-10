-- PBZ Steam build 26266538 only; UE4SS 1183/cdbc0b66, UEPseudo fbb4fdd.
-- EXE SHA-256: 7b4fcd286a350780faf0824d73aa150b21cbf1bccde883e6a96386cbe09973b4
-- Resolve the real bytecode dispatch table, not ProcessLocalScriptFunction.
-- EX_Max is 0xFF: 255 eight-byte entries; index 255 is outside this array.

local Pattern = "48 89 5C 24 20 56 57 41 56 48 83 EC 70 48 8B 05 ?? ?? ?? ?? 48 33 C4 48 89 44 24 60 48 8B 42 20 4C 8D 35 ?? ?? ?? ?? 48 8B 72 10 49 8B F8 48 8B DA 80 38 04 74 40 48 8B D0 0F 1F 80 00 00 00 00 80 BB A1 00 00 00 00 48 8B C2 75 5C 0F B6 0A 48 8D 42 01 48 89 43 20 4C 8D 44 24 20 48 8B D3 4D 8B 0C CE 48 8B 4B 18 41 FF D1 48 8B 43 20 48 8B D0 80 38 04 75 CA 80 BB A1 00 00 00 00 75 29 48 FF C0 48 89 43 20 0F B6 08 48 FF C0 48 89 43 20 80 F9 0B 74 7F 4D 8B 0C CE 4C 8B C7 48 8B 4B 18 48 8B D3 41 FF D1 EB 6C"
local FunctionRVA = 0x01631900
local TableRVA = 0x0D9F9E20
local EntryCount = 0xFF

local function u32(address)
    local value = DerefToInt32(address)
    if value == nil then return nil end
    return value & 0xFFFFFFFF
end

local function rip(address, displacement_offset, next_offset)
    -- DerefToInt32 returns a signed displacement; retain its sign.
    local displacement = DerefToInt32(address + displacement_offset)
    if displacement == nil then return nil end
    return address + next_offset + displacement
end

local function contains(ranges, address, span)
    for _, range in ipairs(ranges) do
        if address >= range[1] and address + span <= range[2] then return true end
    end
    return false
end

function Register()
    return Pattern
end

function OnMatchFound(address)
    local module_base = address - FunctionRVA
    if module_base <= 0 or module_base >= 0x800000000000 or module_base % 0x10000 ~= 0 then return nil end
    local mz, nt_offset = u32(module_base), u32(module_base + 0x3C)
    if mz == nil or (mz & 0xFFFF) ~= 0x5A4D or nt_offset == nil or nt_offset < 0x40 or nt_offset > 0x1000 then return nil end
    local nt = module_base + nt_offset
    if u32(nt) ~= 0x4550 or u32(nt + 8) ~= 1793170810 then return nil end
    local machine_sections, optional_size = u32(nt + 4), u32(nt + 20)
    if machine_sections == nil or optional_size == nil or (machine_sections & 0xFFFF) ~= 0x8664 then return nil end
    local count = machine_sections >> 16
    if count ~= 15 or (optional_size & 0xFFFF) ~= 0xF0 then return nil end
    local magic = u32(nt + 24)
    if magic == nil or (magic & 0xFFFF) ~= 0x20B or u32(nt + 24 + 56) ~= 516243456 then return nil end

    local executable, writable = {}, {}
    local first_section = nt + 24 + 0xF0
    for index = 0, count - 1 do
        local header = first_section + index * 40
        local size, start, flags = u32(header + 8), u32(header + 12), u32(header + 36)
        if size == nil or start == nil or flags == nil or start + size > 516243456 then return nil end
        local range = {module_base + start, module_base + start + size}
        if (flags & 0x20000000) ~= 0 and (flags & 0x40000000) ~= 0 then
            executable[#executable + 1] = range
        elseif (flags & 0xC0000000) == 0xC0000000 then
            writable[#writable + 1] = range
        end
    end
    if not contains(executable, address, 0xA8) then return nil end

    local native_table = rip(address, 0x23, 0x27)
    if native_table == nil or native_table % 8 ~= 0 or native_table - module_base ~= TableRVA then return nil end
    if not contains(writable, native_table, EntryCount * 8) then return nil end

    -- A separate native bytecode dispatcher agrees on the base and ABI.
    local step = module_base + 0x01633E20
    if not contains(executable, step, 0x33) then return nil end
    if u32(step + 4) ~= 0x20428B48 or u32(step + 0x23) ~= 0xC90C8B4D then return nil end
    if u32(step + 0x2B) ~= 0x48D1FF41 or rip(step, 0x0B, 0x0F) ~= native_table then return nil end

    -- Static registration for opcode 1 lies above the table: negative disp32.
    local registration = module_base + 0x0F90B6F5
    if not contains(executable, registration - 7, 14) then return nil end
    local store = u32(registration)
    if store == nil or (store & 0xFFFFFF) ~= 0x058948 then return nil end
    if rip(registration, 3, 7) ~= native_table + 8 then return nil end

    -- The mapped table may still contain valid undefined-opcode handlers during
    -- startup. Check every slot's pointer, without pretending registration ran.
    for index = 0, EntryCount - 1 do
        local slot = native_table + index * 8
        local low, high = u32(slot), u32(slot + 4)
        if low == nil or high == nil then return nil end
        local handler = (high << 32) | low
        if not contains(executable, handler, 1) then return nil end
    end

    print(string.format("[PBZ rc4] GNatives resolved: 0x%X (255 executable entries, Steam build 26266538)", native_table))
    return native_table
end
