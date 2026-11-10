-- PBZNekoCompanion: read reply.txt and drive the subtitle mailbox created by JS.
-- Read-only for the game; does not touch saves or gameplay input.

local READY = "PBZ_NEKO_READY|"
local MSG = "PBZ_NEKO_MSG|"
local CMD = "PBZ_NEKO_CMD|"
local last_id = ""
local last_error = ""

local function find_mailbox()
    for _, object in ipairs(FindAllOf("TextBlock") or {}) do
        if object and object:IsValid() then
            local ok, text = pcall(function() return object:GetText():ToString() end)
            if ok and type(text) == "string"
                and (text:sub(1, #READY) == READY
                    or text:sub(1, #MSG) == MSG
                    or text:sub(1, #CMD) == CMD) then
                return object, text
            end
        end
    end
    return nil, nil
end

local function read_reply(bridge)
    local file = io.open(bridge .. "/reply.txt", "rb")
    if not file then return nil end
    local line = file:read("*a")
    file:close()
    if not line then return nil end
    local id, ts, ttl, body = line:match("^([^|]+)|([^|]+)|([^|]+)|(.*)")
    if not id or not body or body == "" then return nil end
    local age = os.time() - (tonumber(ts) or 0)
    if age > (tonumber(ttl) or 6) then return nil end
    return id, body
end

local function push_tick()
    local mailbox, current = find_mailbox()
    if not mailbox then return end
    if current and current:sub(1, #READY) == READY then
        local bridge = current:sub(#READY + 1)
        local id, body = read_reply(bridge)
        if id and id ~= last_id then
            last_id = id
            ExecuteInGameThread(function()
                pcall(function()
                    mailbox:SetText(FText(MSG .. body .. "|6"))
                end)
            end)
        end
    end
end

LoopAsync(200, function()
    local ok, err = pcall(push_tick)
    if not ok and last_error ~= tostring(err) then
        last_error = tostring(err)
        print("[PBZNekoCompanion] " .. last_error .. "\n")
    end
    return false
end)

RegisterKeyBind(Key.F10, function()
    local mailbox, current = find_mailbox()
    if not mailbox then return end
    if current and current:sub(1, #READY) == READY then
        ExecuteInGameThread(function()
            pcall(function() mailbox:SetText(FText(CMD .. "toggle")) end)
        end)
    end
end)

-- F11: one-shot visual recon request while the game is foreground.
RegisterKeyBind(Key.F11, function()
    local mailbox, current = find_mailbox()
    if not mailbox then return end
    if current and current:sub(1, #READY) == READY then
        local bridge = current:sub(#READY + 1)
        ExecuteInGameThread(function()
            pcall(function()
                local file = io.open(bridge .. "/vision_request.txt", "w")
                if file then
                    file:write(tostring(os.time()))
                    file:close()
                end
            end)
        end)
    end
end)

-- F12: one-shot contextual companion assist; the Python plugin chooses wording.
RegisterKeyBind(Key.F12, function()
    local mailbox, current = find_mailbox()
    if not mailbox then return end
    if current and current:sub(1, #READY) == READY then
        local bridge = current:sub(#READY + 1)
        ExecuteInGameThread(function()
            pcall(function()
                local file = io.open(bridge .. "/assist_request.txt", "w")
                if file then
                    file:write("brief")
                    file:close()
                end
            end)
        end)
    end
end)

print("[PBZNekoCompanion] subtitle bridge loaded\n")
