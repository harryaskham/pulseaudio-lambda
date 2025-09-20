package main

import (
    "bufio"
    "encoding/json"
    "errors"
    "flag"
    "fmt"
    tea "github.com/charmbracelet/bubbletea"
    "github.com/charmbracelet/bubbles/textinput"
    "github.com/charmbracelet/bubbles/viewport"
    "github.com/charmbracelet/lipgloss"
    "bytes"
    "io/fs"
    "math"
    "os"
    "os/exec"
    "path/filepath"
    "strings"
    "syscall"
    "time"
)

type Config struct {
    Checkpoint            string    `json:"checkpoint"`
    ChunkSecs             float64   `json:"chunk_secs"`
    OverlapSecs           float64   `json:"overlap_secs"`
    Gains                 []float64 `json:"gains"`
    Muted                 []bool    `json:"muted"`
    Soloed                []bool    `json:"soloed"`
    Normalize             bool      `json:"normalize"`
    Device                string    `json:"device"`
    Watch                 bool      `json:"watch"`
    Debug                 bool      `json:"debug"`
    EmptyQueuesRequested  string    `json:"empty_queues_requested,omitempty"`
    QueuesLastEmptiedAt   string    `json:"queues_last_emptied_at,omitempty"`
}

func defaultConfig() Config {
    return Config{
        Checkpoint:           "",
        ChunkSecs:            2.0,
        OverlapSecs:          0.5,
        Gains:                []float64{100, 100, 100, 100},
        Muted:                []bool{false, false, false, false},
        Soloed:               []bool{false, false, false, false},
        Normalize:            false,
        Device:               "cpu",
        Watch:                false,
        Debug:                false,
        EmptyQueuesRequested: "",
    }
}

func expandUser(path string) string {
    if path == "" { return path }
    if strings.HasPrefix(path, "~/") || path == "~" {
        home, err := os.UserHomeDir()
        if err == nil {
            if path == "~" { return home }
            return filepath.Join(home, strings.TrimPrefix(path, "~/"))
        }
    }
    return path
}

func configDir() (string, error) {
    if d := os.Getenv("PA_LAMBDA_CONFIG_DIR"); d != "" {
        return d, nil
    }
    home, err := os.UserHomeDir()
    if err != nil { return "", err }
    return filepath.Join(home, ".config", "pulseaudio-lambda"), nil
}

func configPath() (string, error) {
    dir, err := configDir()
    if err != nil { return "", err }
    return filepath.Join(dir, "stream_separator_config.json"), nil
}

func statsPath() (string, error) {
    dir, err := configDir()
    if err != nil { return "", err }
    return filepath.Join(dir, "stream_separator_stats.json"), nil
}

func loadConfig() (Config, string, error) {
    path, err := configPath()
    if err != nil { return Config{}, "", err }
    b, err := os.ReadFile(path)
    if errors.Is(err, fs.ErrNotExist) {
        // create defaults
        if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
            return Config{}, "", err
        }
        cfg := defaultConfig()
        if err := saveConfig(cfg); err != nil {
            return cfg, path, err
        }
        return cfg, path, nil
    } else if err != nil {
        return Config{}, "", err
    }
    var cfg Config
    if err := json.Unmarshal(b, &cfg); err != nil { return Config{}, "", err }
    // ensure lengths
    if len(cfg.Gains) != 4 { cfg.Gains = []float64{100,100,100,100} }
    if len(cfg.Muted) != 4 { cfg.Muted = []bool{false,false,false,false} }
    if len(cfg.Soloed) != 4 { cfg.Soloed = []bool{false,false,false,false} }
    if cfg.Device != "cpu" && cfg.Device != "cuda" { cfg.Device = "cpu" }
    return cfg, path, nil
}

func saveConfig(cfg Config) error {
    path, err := configPath()
    if err != nil { return err }
    if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil { return err }
    b, err := json.MarshalIndent(cfg, "", "    ")
    if err != nil { return err }
    return os.WriteFile(path, b, 0o644)
}

func (c *Config) ResetVolumes() {
    c.Gains = []float64{100,100,100,100}
    c.Muted = []bool{false,false,false,false}
    c.Soloed = []bool{false,false,false,false}
}

func (c *Config) ToggleMute(i int) {
    if i<0 || i>=len(c.Muted) { return }
    c.Muted[i] = !c.Muted[i]
    if c.Muted[i] { c.Soloed[i] = false }
}

func (c *Config) ToggleSolo(i int) {
    if i<0 || i>=len(c.Soloed) { return }
    c.Soloed[i] = !c.Soloed[i]
    if c.Soloed[i] { c.Muted[i] = false }
}

func (c *Config) RequestEmptyQueues() {
    c.EmptyQueuesRequested = time.Now().Format(time.RFC3339Nano)
}

// UI

type slider struct {
    Label string
    Value float64
    Min   float64
    Max   float64
    Step  float64
    Unit  string // "%" or "s"
}

func (s *slider) Inc() { s.Value = clamp(s.Value + s.Step, s.Min, s.Max) }
func (s *slider) Dec() { s.Value = clamp(s.Value - s.Step, s.Min, s.Max) }
func (s *slider) Render(width int) string {
    // draw [====|----] label value
    barW := max(10, width-24)
    pos := 0
    if s.Max > s.Min {
        pos = int(math.Round((s.Value - s.Min) / (s.Max - s.Min) * float64(barW-1)))
        if pos < 0 { pos = 0 }
        if pos >= barW { pos = barW-1 }
    }
    b := strings.Repeat("=", pos) + "|" + strings.Repeat("-", barW-pos-1)
    val := fmt.Sprintf("%.0f%s", s.Value, s.Unit)
    if s.Unit == "s" { val = fmt.Sprintf("%.1fs", s.Value) }
    return fmt.Sprintf("%-14s [%s] %6s", s.Label+":", b, val)
}

type msgSave struct{}
type msgStatsTick struct{}
type msgLogPoll struct{}

type model struct {
    cfg      Config
    focused  int
    width    int
    height   int
    // UI components
    gain     [4]*slider
    chunk    *slider
    overlap  *slider
    chkpt    textinput.Model
    // debounce
    pendingSave bool

    // live stats
    stats       Stats
    prevStats   Stats
    lastStatsAt time.Time
    inBps       float64
    outBps      float64
    rtf         float64 // processed seconds per wall second
    hist        []rateSample

    // mouse/hit testing
    hits []hitArea

    // service status
    serviceRunning bool

    // logs viewport
    showLogs bool
    vp       viewport.Model
    logs     []string
    logCh    chan string
    childCmd *exec.Cmd
    followTail bool
    childPGID int

    // startup
    autoStart bool
    serviceDebug bool
}

type rateSample struct {
    t    time.Time
    in   float64
    out  float64
    proc float64
}

func initialModel() model {
    cfg, _, _ := loadConfig()
    m := model{cfg: cfg}
    for i := 0; i < 4; i++ {
        m.gain[i] = &slider{Label: []string{"Drums","Bass","Vocals","Other"}[i], Value: cfg.Gains[i], Min: 0, Max: 200, Step: 1, Unit: "%"}
    }
    m.chunk = &slider{Label: "Chunk Size", Value: cfg.ChunkSecs, Min: 0.1, Max: 30.0, Step: 0.1, Unit: "s"}
    m.overlap = &slider{Label: "Overlap", Value: cfg.OverlapSecs, Min: 0.0, Max: 5.0, Step: 0.1, Unit: "s"}
    ti := textinput.New()
    ti.Placeholder = "~/path/to/checkpoint.pt"
    ti.SetValue(cfg.Checkpoint)
    ti.Prompt = ""
    ti.CharLimit = 4096
    ti.Width = 60
    m.chkpt = ti
    m.vp = viewport.Model{Width: 80, Height: 10}
    m.logCh = make(chan string, 1024)
    m.followTail = true

    return m
}

var (
    // Nord palette
    nord0 = lipgloss.Color("#2E3440")
    nord1 = lipgloss.Color("#3B4252")
    nord2 = lipgloss.Color("#434C5E")
    nord3 = lipgloss.Color("#4C566A")
    nord4 = lipgloss.Color("#D8DEE9")
    nord7 = lipgloss.Color("#8FBCBB")
    nord8 = lipgloss.Color("#88C0D0")
    nord9 = lipgloss.Color("#81A1C1")
    nord10 = lipgloss.Color("#5E81AC")
    nord11 = lipgloss.Color("#BF616A")
    nord13 = lipgloss.Color("#EBCB8B")
    nord14 = lipgloss.Color("#A3BE8C")

    titleStyle   = lipgloss.NewStyle().Bold(true).Foreground(nord8)
    sectionStyle = lipgloss.NewStyle().MarginTop(1).Foreground(nord9)
    focusStyle   = lipgloss.NewStyle().Foreground(nord13)
    btnStyle     = lipgloss.NewStyle().Padding(0,1).Foreground(nord4).Background(nord2)
    btnOnStyle   = lipgloss.NewStyle().Padding(0,1).Foreground(nord0).Background(nord10)
    warnStyle    = lipgloss.NewStyle().Padding(0,1).Foreground(nord0).Background(nord11)
    panelStyle   = lipgloss.NewStyle().Border(lipgloss.RoundedBorder()).BorderForeground(nord3).Padding(0, 1).Margin(0, 0, 1, 0)
    btnFocusStyle= lipgloss.NewStyle().Padding(0,1).Bold(true).Underline(true).Foreground(nord4).Background(nord3)
    focusWrap    = lipgloss.NewStyle().Background(nord1)
)

func (m *model) Init() tea.Cmd {
    if m.autoStart {
        return tea.Batch(m.startChild(), m.scheduleStats())
    }
    return m.scheduleStats()
}

func (m *model) scheduleSave() tea.Cmd {
    if m.pendingSave { return nil }
    m.pendingSave = true
    return tea.Tick(200*time.Millisecond, func(time.Time) tea.Msg { return msgSave{} })
}

func (m *model) scheduleStats() tea.Cmd {
    return tea.Tick(1*time.Second, func(time.Time) tea.Msg { return msgStatsTick{} })
}

func (m *model) scheduleLogPoll() tea.Cmd {
    return tea.Tick(100*time.Millisecond, func(time.Time) tea.Msg { return msgLogPoll{} })
}

func (m *model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.MouseMsg:
        // Prefer new MouseAction/MouseButton if available; fallback to Type for compat
        // Wheel over sliders adjusts that slider; otherwise scroll focus.
        if msg.Action == tea.MouseActionPress && msg.Button == tea.MouseButtonLeft || msg.Type == tea.MouseLeft {
            for _, h := range m.hits {
                if msg.X >= h.x1 && msg.X <= h.x2 && msg.Y >= h.y1 && msg.Y <= h.y2 {
                    return m.handleHit(h, msg.X)
                }
            }
            return m, nil
        }
        if msg.Action == tea.MouseActionMotion && msg.Button == tea.MouseButtonLeft || msg.Type == tea.MouseMotion {
            // Dragging on a slider: update its value continuously
            for _, h := range m.hits {
                if (h.kind == hitSliderVolume || h.kind == hitSliderChunk || h.kind == hitSliderOverlap) &&
                    msg.X >= h.x1 && msg.X <= h.x2 && msg.Y >= h.y1 && msg.Y <= h.y2 {
                    return m.handleHit(h, msg.X)
                }
            }
            return m, nil
        }
        if msg.Button == tea.MouseButtonWheelUp || msg.Type == tea.MouseWheelUp {
            if m.showLogs { m.followTail = false }
            // If over a slider, adjust it; else move focus
            for _, h := range m.hits {
                if msg.X >= h.x1 && msg.X <= h.x2 && msg.Y >= h.y1 && msg.Y <= h.y2 {
                    switch h.kind {
                    case hitSliderVolume:
                        m.gain[h.index].Inc(); m.cfg.Gains[h.index] = m.gain[h.index].Value; return m, m.scheduleSave()
                    case hitSliderChunk:
                        m.chunk.Inc(); m.cfg.ChunkSecs = round1(m.chunk.Value); return m, m.scheduleSave()
                    case hitSliderOverlap:
                        m.overlap.Inc(); m.cfg.OverlapSecs = round1(m.overlap.Value); return m, m.scheduleSave()
                    }
                }
            }
            if m.focused > 0 { m.focused-- }
            if m.showLogs {
                var cmd tea.Cmd
                m.vp, cmd = m.vp.Update(msg)
                return m, cmd
            }
            return m, nil
        }
        if msg.Button == tea.MouseButtonWheelDown || msg.Type == tea.MouseWheelDown {
            for _, h := range m.hits {
                if msg.X >= h.x1 && msg.X <= h.x2 && msg.Y >= h.y1 && msg.Y <= h.y2 {
                    switch h.kind {
                    case hitSliderVolume:
                        m.gain[h.index].Dec(); m.cfg.Gains[h.index] = m.gain[h.index].Value; return m, m.scheduleSave()
                    case hitSliderChunk:
                        m.chunk.Dec(); m.cfg.ChunkSecs = round1(m.chunk.Value); return m, m.scheduleSave()
                    case hitSliderOverlap:
                        m.overlap.Dec(); m.cfg.OverlapSecs = round1(m.overlap.Value); return m, m.scheduleSave()
                    }
                }
            }
            m.focused++
            if m.focused > m.maxFocus() { m.focused = m.maxFocus() }
            // also forward to viewport for scroll-on-hover if logs visible
            if m.showLogs {
                var cmd tea.Cmd
                m.vp, cmd = m.vp.Update(msg)
                return m, cmd
            }
            return m, nil
        }
    case tea.KeyMsg:
        switch msg.String() {
        case "ctrl+c", "q":
            return m, tea.Quit
        case "up":
            m.focused = m.prevFocus()
        case "down":
            m.focused = m.nextFocus()
        case "left":
            // Per-stem focus order: vol, mute, solo
            if m.focused >= 0 && m.focused < 12 {
                stem := m.focused / 3
                which := m.focused % 3
                if which == 0 {
                    m.gain[stem].Dec(); m.cfg.Gains[stem] = m.gain[stem].Value; return m, m.scheduleSave()
                }
            }
            switch m.focused {
            case 13:
                m.chunk.Dec(); m.cfg.ChunkSecs = round1(m.chunk.Value); return m, m.scheduleSave()
            case 14:
                m.overlap.Dec(); m.cfg.OverlapSecs = round1(m.overlap.Value); return m, m.scheduleSave()
            }
        case "right":
            if m.focused >= 0 && m.focused < 12 {
                stem := m.focused / 3
                which := m.focused % 3
                if which == 0 {
                    m.gain[stem].Inc(); m.cfg.Gains[stem] = m.gain[stem].Value; return m, m.scheduleSave()
                }
            }
            switch m.focused {
            case 13:
                m.chunk.Inc(); m.cfg.ChunkSecs = round1(m.chunk.Value); return m, m.scheduleSave()
            case 14:
                m.overlap.Inc(); m.cfg.OverlapSecs = round1(m.overlap.Value); return m, m.scheduleSave()
            }
        case "enter", " ":
            if m.focused >= 0 && m.focused < 12 {
                stem := m.focused / 3
                which := m.focused % 3
                if which == 1 { // mute
                    m.cfg.ToggleMute(stem)
                    return m, m.scheduleSave()
                } else if which == 2 { // solo
                    m.cfg.ToggleSolo(stem)
                    return m, m.scheduleSave()
                }
            }
            switch m.focused {
            case 15:
                m.cfg.Device = "cpu"; return m, m.scheduleSave()
            case 16:
                m.cfg.Device = "cuda"; return m, m.scheduleSave()
            case 17:
                m.cfg.Normalize = !m.cfg.Normalize; return m, m.scheduleSave()
            case 12: m.cfg.ResetVolumes(); for i:=0;i<4;i++{ m.gain[i].Value = 100 }; return m, m.scheduleSave()
            case 18: m.cfg.RequestEmptyQueues(); return m, m.scheduleSave()
            case 20:
                if m.serviceRunning {
                    if m.childCmd != nil { m.stopChild() } else { stopServiceAsync() }
                    return m, nil
                }
                return m, m.startChild()
            case 21:
                if m.childCmd != nil {
                    m.showLogs = !m.showLogs
                    if m.showLogs { m.followTail = true }
                }
                return m, nil
            }
        // no explicit save button/hotkey; autosave is default
        case "r": m.cfg.ResetVolumes(); for i:=0;i<4;i++{ m.gain[i].Value = 100 }; return m, m.scheduleSave()
        case "e": m.cfg.RequestEmptyQueues(); return m, m.scheduleSave()
        case "n": m.cfg.Normalize = !m.cfg.Normalize; return m, m.scheduleSave()
        case "l":
            if m.childCmd != nil {
                m.showLogs = !m.showLogs
                if m.showLogs { m.followTail = true }
            }
            return m, nil
        case "d":
            i := 0; m.cycleStemState(i); return m, m.scheduleSave()
        case "b":
            i := 1; m.cycleStemState(i); return m, m.scheduleSave()
        case "v":
            i := 2; m.cycleStemState(i); return m, m.scheduleSave()
        case "o":
            i := 3; m.cycleStemState(i); return m, m.scheduleSave()
        }
        // Forward other keys to logs viewport when visible
        if m.showLogs {
            switch msg.String() {
            case "pgup", "home", "up", "k":
                m.followTail = false
            case "end":
                m.followTail = true
            }
            var cmd tea.Cmd
            m.vp, cmd = m.vp.Update(msg)
            return m, cmd
        }
    case tea.WindowSizeMsg:
        m.width = msg.Width; m.height = msg.Height
    case msgSave:
        m.pendingSave = false
        _ = saveConfig(m.cfg)
        return m, nil
    case msgStatsTick:
        // Load stats and compute simple rates
        now := time.Now()
        s := loadStats()
        // Update moving window history (30s) and compute moving-average rates
        m.hist = append(m.hist, rateSample{t: now, in: s.InputBytes, out: s.OutputBytes, proc: s.ProcessedSecs})
        // prune
        cutoff := now.Add(-30 * time.Second)
        i := 0
        for i < len(m.hist) && m.hist[i].t.Before(cutoff) { i++ }
        if i > 0 && i < len(m.hist) { m.hist = append([]rateSample{}, m.hist[i:]...) } else if i >= len(m.hist) { m.hist = nil }
        if len(m.hist) >= 2 {
            first := m.hist[0]
            last := m.hist[len(m.hist)-1]
            dt := last.t.Sub(first.t).Seconds()
            if dt > 0.001 {
                m.inBps = maxf((last.in-first.in)/dt, 0)
                m.outBps = maxf((last.out-first.out)/dt, 0)
                m.rtf = maxf((last.proc-first.proc)/dt, 0)
            }
        }
        m.prevStats = m.stats
        m.stats = s
        m.lastStatsAt = now
        m.serviceRunning = isServiceRunning()
        return m, m.scheduleStats()
    case msgLogPoll:
        if m.childCmd != nil && m.logCh != nil {
            drained := false
            for i:=0; i<512; i++ {
                select {
                case line := <-m.logCh:
                    m.logs = append(m.logs, line)
                    drained = true
                default:
                    i = 512; // break
                }
            }
            if drained {
                if len(m.logs) > 2000 { m.logs = m.logs[len(m.logs)-2000:] }
                m.vp.SetContent(strings.Join(m.logs, "\n"))
                if m.followTail { m.vp.GotoBottom() }
            }
            return m, m.scheduleLogPoll()
        }
        return m, nil
    }

    // textinput update when focused
    if m.focused == 19 {
        var cmd tea.Cmd
        old := m.chkpt.Value()
        m.chkpt, cmd = m.chkpt.Update(msg)
        if m.chkpt.Value() != old {
            m.cfg.Checkpoint = m.chkpt.Value()
            return m, m.scheduleSave()
        }
        return m, cmd
    }

    return m, nil
}

// Cycle a stem through: neither -> mute -> solo -> neither
func (m *model) cycleStemState(i int) {
    if i < 0 || i > 3 { return }
    muted := m.cfg.Muted[i]
    solo := m.cfg.Soloed[i]
    if !muted && !solo {
        m.cfg.Muted[i] = true
        m.cfg.Soloed[i] = false
    } else if muted {
        m.cfg.Muted[i] = false
        m.cfg.Soloed[i] = true
    } else {
        m.cfg.Muted[i] = false
        m.cfg.Soloed[i] = false
    }
}

type hitKind int
const (
    hitSliderVolume hitKind = iota
    hitToggleMute
    hitToggleSolo
    hitBtnReset
    hitSliderChunk
    hitSliderOverlap
    hitRadioCPU
    hitRadioCUDA
    hitToggleNormalize
    hitBtnEmpty
    hitTextCheckpoint
    hitBtnStart
    hitBtnStop
    hitBtnLogs
)

type hitArea struct { x1, y1, x2, y2 int; kind hitKind; index int; }

func (m *model) handleHit(h hitArea, clickX int) (tea.Model, tea.Cmd) {
    switch h.kind {
    case hitSliderVolume:
        m.focused = 3*h.index + 0
        // Map X to slider value. Bracket starts at x1.
        barW := max(10, (m.width-6)-24)
        clicked := clampf(float64(clickX-h.x1), 0, float64(barW-1))
        // Compute value from click position
        v := m.gain[h.index]
        if v == nil { return m, nil }
        ratio := clicked / float64(barW-1)
        v.Value = v.Min + ratio*(v.Max-v.Min)
        m.cfg.Gains[h.index] = v.Value
        return m, m.scheduleSave()
    case hitToggleMute:
        m.focused = 3*h.index + 1
        m.cfg.ToggleMute(h.index)
        return m, m.scheduleSave()
    case hitToggleSolo:
        m.focused = 3*h.index + 2
        m.cfg.ToggleSolo(h.index)
        return m, m.scheduleSave()
    case hitBtnReset:
        m.focused = 12
        m.cfg.ResetVolumes(); for i:=0;i<4;i++{ m.gain[i].Value = 100 }
        return m, m.scheduleSave()
    case hitSliderChunk:
        m.focused = 13
        barW := max(10, (m.width-6)-24)
        clicked := clampf(float64(clickX-h.x1), 0, float64(barW-1))
        ratio := clicked / float64(barW-1)
        m.chunk.Value = m.chunk.Min + ratio*(m.chunk.Max-m.chunk.Min)
        m.cfg.ChunkSecs = round1(m.chunk.Value)
        return m, m.scheduleSave()
    case hitSliderOverlap:
        m.focused = 14
        barW := max(10, (m.width-6)-24)
        clicked := clampf(float64(clickX-h.x1), 0, float64(barW-1))
        ratio := clicked / float64(barW-1)
        m.overlap.Value = m.overlap.Min + ratio*(m.overlap.Max-m.overlap.Min)
        m.cfg.OverlapSecs = round1(m.overlap.Value)
        return m, m.scheduleSave()
    case hitRadioCPU:
        m.focused = 15
        m.cfg.Device = "cpu"
        return m, m.scheduleSave()
    case hitRadioCUDA:
        m.focused = 16
        m.cfg.Device = "cuda"
        return m, m.scheduleSave()
    case hitToggleNormalize:
        m.focused = 17
        m.cfg.Normalize = !m.cfg.Normalize
        return m, m.scheduleSave()
    case hitBtnEmpty:
        m.focused = 18
        m.cfg.RequestEmptyQueues()
        return m, m.scheduleSave()
    case hitTextCheckpoint:
        // Focus the text input
        m.focused = 19
        return m, nil
    case hitBtnStart:
        m.focused = 20
        return m, m.startChild()
    case hitBtnStop:
        m.focused = 20
        if m.childCmd != nil { m.stopChild() } else { stopServiceAsync() }
        return m, nil
    case hitBtnLogs:
        m.focused = 21
        m.showLogs = !m.showLogs
        return m, nil
    }
    return m, nil
}

func (m model) View() string {
    // Compute a conservative inner width so content never exceeds the viewport.
    // Account for panel borders and padding; also cap bar widths to avoid overflow.
    w := max(40, m.width-8)
    b := &strings.Builder{}
    m.hits = nil
    fmt.Fprintln(b, titleStyle.Render("paλ-stem-separator"))
    curY := 1 // title occupies first line

    // Live Stats
    sb := &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Live Stats"))
    // Latency bar (target 45s scale) with chunk marker
    latency := m.stats.LatencySecs
    fmt.Fprintln(sb, "  Latency:")
    barW := max(10, w-10)
    fmt.Fprintln(sb, "   "+renderBarWithMarker(latency/45.0, barW, latencyLabel(latency), latencyColor(latency), m.cfg.ChunkSecs/45.0))
    // Throughput and speed
    fmt.Fprintf(sb, "  %s    %s    RTF: %.2fx\n", formatRate("In", m.inBps), formatRate("Out", m.outBps), m.rtf)
    // Raw totals
    fmt.Fprintf(sb, "  Input:     %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.InputBytes), formatInt(m.stats.InputSamples), m.stats.InputSecs)
    fmt.Fprintf(sb, "  Processed: %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.ProcessedBytes), formatInt(m.stats.ProcessedSamples), m.stats.ProcessedSecs)
    fmt.Fprintf(sb, "  Output:    %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.OutputBytes), formatInt(m.stats.OutputSamples), m.stats.OutputSecs)
    // Service status and logs toggle
    var svc string
    if m.serviceRunning { svc = lipgloss.NewStyle().Foreground(nord14).Render("Running") } else { svc = lipgloss.NewStyle().Foreground(nord11).Render("Stopped") }
    svcLabel := "Start"; if m.serviceRunning { svcLabel = "Stop" }
    svcStyle := btnStyle; if m.focused == 20 { svcStyle = btnFocusStyle }
    svcBtn := svcStyle.Render(svcLabel)
    var logsUI string
    if m.childCmd != nil {
        logsLabel := "Show Logs"; if m.showLogs { logsLabel = "Hide Logs" }
        logsStyle := btnStyle; if m.focused == 21 { logsStyle = btnFocusStyle }
        logsUI = logsStyle.Render(logsLabel)
    } else {
        logsUI = lipgloss.NewStyle().Faint(true).Render("<logs unavailable>")
    }
    fmt.Fprintln(sb, "  Service: "+svc+"  "+svcBtn+"  "+logsUI)
    // Service Start button hit area if stopped
    if !m.serviceRunning {
        // Approximate start button position: last line of sb
        // We will add a broad hit area near the end of the panel line
        // The precise position is estimated further below after printing panel
    }
    livePanel := panelStyle.Render(sb.String())
    fmt.Fprintln(b, livePanel)
    // advance Y by panel height (content lines + 2 borders + 1 margin)
    liveLines := strings.Count(sb.String(), "\n") + 1
    curY += liveLines + 3
    // approximate a clickable region for Start/Stop and Logs on the last content line within the panel
    btnY := curY - 3
    if m.serviceRunning { m.hits = append(m.hits, hitArea{ x1: 2, y1: btnY, x2: 2 + w/3, y2: btnY, kind: hitBtnStop }) }
    if !m.serviceRunning { m.hits = append(m.hits, hitArea{ x1: 2, y1: btnY, x2: 2 + w/3, y2: btnY, kind: hitBtnStart }) }
    if m.childCmd != nil {
        m.hits = append(m.hits, hitArea{ x1: 2 + w/3 + 2, y1: btnY, x2: 2 + w, y2: btnY, kind: hitBtnLogs })
    }

    // Logs viewport (optional)
    if m.showLogs {
        m.vp.Width = w
        m.vp.Height = 10
        fmt.Fprintln(b, panelStyle.Render("Logs\n"+m.vp.View()))
        curY += m.vp.Height + 3
    }

    // Volume Controls
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Stem Volumes"))
    baseY := curY + 1 // first content line inside panel
    baseX := 2        // border + padding
    lineOfs := 1      // after header
    barW = max(10, w-10)
    for i := 0; i < 4; i++ {
        volIdx := 3*i + 0
        muteIdx := 3*i + 1
        soloIdx := 3*i + 2
        line := m.gain[i].Render(w)
        if m.focused == volIdx { line = focusStyle.Render(line) }
        fmt.Fprintln(sb, " "+line)
        // hit area for volume slider bar (inside brackets)
        y := baseY + lineOfs
        x1 := baseX + 1 + 15 + 1 // indent + label field + '[' inner start
        x2 := x1 + barW - 1
        m.hits = append(m.hits, hitArea{ x1: x1, y1: y, x2: x2, y2: y, kind: hitSliderVolume, index: i })
        // mute / solo as single-line toggles
        mute := renderToggle("Mute", m.cfg.Muted[i], m.focused == muteIdx, nord11, nord4)
        solo := renderToggle("Solo", m.cfg.Soloed[i], m.focused == soloIdx, nord13, nord4)
        btns := lipgloss.JoinHorizontal(lipgloss.Top, mute, "  ", solo)
        fmt.Fprintln(sb, "   "+btns)
        // approximate hit areas for mute/solo
        y2 := y + 1
        m.hits = append(m.hits, hitArea{ x1: baseX + 3, y1: y2, x2: baseX + 3 + 10, y2: y2, kind: hitToggleMute, index: i })
        m.hits = append(m.hits, hitArea{ x1: baseX + 3 + 12, y1: y2, x2: baseX + 3 + 22, y2: y2, kind: hitToggleSolo, index: i })
        lineOfs += 2
    }
    // Reset (placed immediately after volumes)
    reset := btnStyle.Render("Reset All Volumes")
    if m.focused == 12 { reset = btnFocusStyle.Render("Reset All Volumes") }
    fmt.Fprintln(sb, "  "+reset)
    // hit area for reset button (full line)
    m.hits = append(m.hits, hitArea{ x1: baseX, y1: baseY + lineOfs, x2: baseX + w, y2: baseY + lineOfs, kind: hitBtnReset })
    fmt.Fprintln(b, panelStyle.Render(sb.String()))
    volLines := lineOfs + 2 // + header and reset line
    curY += volLines + 2 + 1 // borders + margin

    // Processing settings
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Processing Settings"))
    baseY = curY + 1; baseX = 2; lineOfs = 1
    line := m.chunk.Render(w); if m.focused==13 { line = focusStyle.Render(line) }; fmt.Fprintln(sb, " "+line)
    // chunk hit
    y := baseY + lineOfs; x1 := baseX + 1 + 15 + 1; x2 := x1 + barW - 1
    m.hits = append(m.hits, hitArea{ x1: x1, y1: y, x2: x2, y2: y, kind: hitSliderChunk })
    lineOfs++
    line = m.overlap.Render(w); if m.focused==14 { line = focusStyle.Render(line) }; fmt.Fprintln(sb, " "+line)
    // overlap hit
    y = baseY + lineOfs; x1 = baseX + 1 + 15 + 1; x2 = x1 + barW - 1
    m.hits = append(m.hits, hitArea{ x1: x1, y1: y, x2: x2, y2: y, kind: hitSliderOverlap })
    lineOfs++
    // Device
    cpu := renderRadio("CPU", m.cfg.Device=="cpu", m.focused==15)
    cuda := renderRadio("CUDA", m.cfg.Device=="cuda", m.focused==16)
    deviceBtns := lipgloss.JoinHorizontal(lipgloss.Top, cpu, "  ", cuda)
    fmt.Fprintln(sb, "  Device: "+deviceBtns)
    // rough hit areas for CPU/CUDA radios
    y = baseY + lineOfs; m.hits = append(m.hits, hitArea{ x1: baseX + 12, y1: y, x2: baseX + 20, y2: y, kind: hitRadioCPU })
    m.hits = append(m.hits, hitArea{ x1: baseX + 24, y1: y, x2: baseX + 32, y2: y, kind: hitRadioCUDA })
    lineOfs++
    // Normalize
    norm := renderToggle("Normalize", m.cfg.Normalize, m.focused==17, nord14, nord4)
    fmt.Fprintln(sb, "  "+norm)
    y = baseY + lineOfs; m.hits = append(m.hits, hitArea{ x1: baseX + 2, y1: y, x2: baseX + 18, y2: y, kind: hitToggleNormalize })
    lineOfs++
    // Empty queues
    empty := btnStyle.Render("Empty Queues"); if m.focused==18 { empty = btnFocusStyle.Render("Empty Queues") }
    fmt.Fprintln(sb, "  "+empty)
    y = baseY + lineOfs; m.hits = append(m.hits, hitArea{ x1: baseX, y1: y, x2: baseX + w, y2: y, kind: hitBtnEmpty })
    fmt.Fprintln(b, panelStyle.Render(sb.String()))
    procLines := lineOfs + 1 // + header assumed already counted in lineOfs start
    curY += procLines + 2 + 1

    // Checkpoint
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Model Checkpoint"))
    ti := m.chkpt.View(); if m.focused==19 { ti = focusWrap.Render(ti) }
    fmt.Fprintln(sb, "  "+ti)
    fmt.Fprintln(b, panelStyle.Render(sb.String()))
    // checkpoint hit (focus)
    baseY = curY + 1; baseX = 2
    m.hits = append(m.hits, hitArea{ x1: baseX, y1: baseY + 1, x2: baseX + w, y2: baseY + 1, kind: hitTextCheckpoint })
    chkLines := strings.Count(sb.String(), "\n") + 1
    curY += chkLines + 2 + 1

    return b.String()
}

func clamp(v, lo, hi float64) float64 { if v<lo {return lo}; if v>hi {return hi}; return v }
func max(a,b int) int { if a>b {return a}; return b }
func round1(v float64) float64 { return math.Round(v*10)/10 }

// Single-line toggle [ ] Label or [x] Label with color accents
func renderToggle(label string, checked bool, focused bool, on lipgloss.Color, off lipgloss.Color) string {
    box := "[ ]"
    style := lipgloss.NewStyle().Foreground(off)
    if checked {
        box = "[x]"
        style = style.Copy().Foreground(on)
    }
    out := style.Render(fmt.Sprintf("%s %s", box, label))
    if focused { out = focusWrap.Render(out) }
    return out
}

// Single-line radio ( ) Label or (•) Label
func renderRadio(label string, selected bool, focused bool) string {
    dot := "( )"
    style := lipgloss.NewStyle().Foreground(nord4)
    if selected { dot = "(•)"; style = style.Copy().Foreground(nord10) }
    out := style.Render(fmt.Sprintf("%s %s", dot, label))
    if focused { out = focusWrap.Render(out) }
    return out
}

// Stats loading/types
type Stats struct {
    InputBytes      float64 `json:"input_bytes"`
    InputSamples    float64 `json:"input_samples"`
    InputSecs       float64 `json:"input_secs"`
    ProcessedBytes  float64 `json:"processed_bytes"`
    ProcessedSamples float64 `json:"processed_samples"`
    ProcessedSecs   float64 `json:"processed_secs"`
    OutputBytes     float64 `json:"output_bytes"`
    OutputSamples   float64 `json:"output_samples"`
    OutputSecs      float64 `json:"output_secs"`
    LatencySecs     float64 `json:"latency_secs"`
}

func loadStats() Stats {
    p, err := statsPath()
    if err != nil { return Stats{} }
    b, err := os.ReadFile(p)
    if err != nil { return Stats{} }
    var s Stats
    if err := json.Unmarshal(b, &s); err != nil { return Stats{} }
    return s
}

// Rendering helpers
func renderBar(ratio float64, width int, label string, color lipgloss.Color) string {
    if width < 10 { width = 10 }
    r := clamp(ratio, 0, 1)
    filled := int(math.Round(r * float64(width)))
    if filled > width { filled = width }
    bar := strings.Repeat("█", filled) + strings.Repeat("░", width-filled)
    style := lipgloss.NewStyle().Foreground(color)
    return style.Render(fmt.Sprintf("[%s] %s", bar, label))
}

func renderBarWithMarker(ratio float64, width int, label string, color lipgloss.Color, markerRatio float64) string {
    if width < 10 { width = 10 }
    r := clamp(ratio, 0, 1)
    filled := int(math.Round(r * float64(width)))
    if filled > width { filled = width }
    barRunes := []rune(strings.Repeat("█", filled) + strings.Repeat("░", width-filled))
    mpos := int(math.Round(clamp(markerRatio, 0, 1) * float64(width-1)))
    if mpos >= 0 && mpos < len(barRunes) {
        barRunes[mpos] = '│'
    }
    style := lipgloss.NewStyle().Foreground(color)
    // Put label on a separate line to avoid overflow in narrow terminals
    return style.Render(fmt.Sprintf("[%s]\n     %s", string(barRunes), label))
}

func latencyLabel(s float64) string { return fmt.Sprintf("%.2f s", s) }
func latencyColor(s float64) lipgloss.Color {
    if s >= 45.0 { return nord11 } // red at/exceed max window
    if s >= 40.0 { return nord13 } // amber when approaching end
    return nord14                 // green
}
func maxf(a, b float64) float64 { if a>b {return a}; return b }
func clampf(v, lo, hi float64) float64 { if v<lo {return lo}; if v>hi {return hi}; return v }
func minInt(a, b int) int { if a<b {return a}; return b }

// Formatting helpers
func formatBytes(b float64) string {
    abs := math.Abs(b)
    unit := "B"
    val := b
    if abs >= 1024*1024*1024 {
        unit = "GB"; val = b / (1024*1024*1024)
    } else if abs >= 1024*1024 {
        unit = "MB"; val = b / (1024*1024)
    } else if abs >= 1024 {
        unit = "kB"; val = b / 1024
    }
    if unit == "B" {
        return fmt.Sprintf("%.0f %s", val, unit)
    }
    return fmt.Sprintf("%.2f %s", val, unit)
}

func formatRate(prefix string, bytesPerSec float64) string {
    // bytesPerSec may be derived from kB/s previously; normalize
    abs := math.Abs(bytesPerSec)
    unit := "B/s"
    val := bytesPerSec
    if abs >= 1024*1024 {
        unit = "MB/s"; val = bytesPerSec / (1024*1024)
    } else if abs >= 1024 {
        unit = "kB/s"; val = bytesPerSec / 1024
    }
    return fmt.Sprintf("%s %s %s", prefix, fmt.Sprintf("%.1f", val), unit)
}

func formatInt(n float64) string {
    // format as integer with commas
    x := int64(math.Round(n))
    neg := x < 0
    if neg { x = -x }
    s := fmt.Sprintf("%d", x)
    var out []byte
    for i, c := range []byte(s) {
        out = append(out, c)
        if (len(s)-i-1)%3 == 0 && i != len(s)-1 {
            out = append(out, ',')
        }
    }
    if neg { return "-" + string(out) }
    return string(out)
}

func main() {
    autoService := false
    fs := flag.NewFlagSet("pal-stem-separator-tui", flag.ContinueOnError)
    serviceDebug := false
    fs.BoolVar(&autoService, "service", false, "Start service on launch (show logs)")
    fs.BoolVar(&serviceDebug, "debug", false, "Run service with --debug")
    _ = fs.Parse(os.Args[1:])

    m := initialModel()
    m.autoStart = autoService
    m.serviceDebug = serviceDebug
    // Kick off stats polling immediately and enable mouse tracking
    p := tea.NewProgram(&m, tea.WithAltScreen(), tea.WithMouseAllMotion())
    if _, err := p.Run(); err != nil {
        fmt.Fprintf(os.Stderr, "error: %v\n", err)
        os.Exit(1)
    }
}

// Dynamic max focus index depending on whether Start is visible
func (m model) maxFocus() int { return 21 }

func (m model) focusOrder() []int {
    order := []int{20}
    if m.childCmd != nil { order = append(order, 21) }
    // stems vol/mute/solo
    for i:=0; i<12; i++ { order = append(order, i) }
    order = append(order, 12,13,14,15,16,17,18,19)
    return order
}

func (m model) nextFocus() int {
    order := m.focusOrder()
    cur := m.focused
    idx := 0
    for i, v := range order { if v == cur { idx = i; break } }
    if idx < len(order)-1 { return order[idx+1] }
    return order[idx]
}

func (m model) prevFocus() int {
    order := m.focusOrder()
    cur := m.focused
    idx := 0
    for i, v := range order { if v == cur { idx = i; break } }
    if idx > 0 { return order[idx-1] }
    return order[idx]
}

func isServiceRunning() bool {
    // Prefer scanning /proc cmdline to match regex "pal-stem-separator$" in any argv segment
    pids := findServicePIDs()
    if len(pids) > 0 { return true }
    // Fallback: simple pgrep
    if _, err := exec.LookPath("pgrep"); err == nil {
        if err := exec.Command("pgrep", "-f", "pal-stem-separator$").Run(); err == nil {
            return true
        }
    }
    return false
}

func matchServiceCmdline(cmdline []byte) bool {
    parts := bytes.Split(cmdline, []byte{0})
    for _, p := range parts {
        if len(p) == 0 { continue }
        s := string(p)
        base := filepath.Base(s)
        // Match python-wrapped pal-stem-separator in argv
        if base == "pal-stem-separator" || strings.HasSuffix(s, "/pal-stem-separator") {
            return true
        }
        // Match explicit subcommand invocations we spawn when --debug is set
        if s == "stem-separator" || s == "stem-separator --debug" {
            return true
        }
    }
    return false
}

func findServicePIDs() []int {
    var pids []int
    d, err := os.ReadDir("/proc")
    if err != nil { return nil }
    for _, e := range d {
        if !e.IsDir() { continue }
        name := e.Name()
        // only numeric PIDs
        if len(name) == 0 || name[0] < '0' || name[0] > '9' { continue }
        b, err := os.ReadFile(filepath.Join("/proc", name, "cmdline"))
        if err == nil && matchServiceCmdline(b) {
            pids = append(pids, toInt(name))
        }
    }
    return pids
}

func startServiceAsync() {
    // Launch: pulseaudio-lambda pal-stem-separator
    cmd := exec.Command("pulseaudio-lambda", "pal-stem-separator")
    // Detach from TUI session
    cmd.Stdout = nil
    cmd.Stderr = nil
    cmd.Stdin = nil
    cmd.SysProcAttr = &syscall.SysProcAttr{Setsid: true}
    _ = cmd.Start()
}

func stopServiceAsync() {
    // Try pkill -f 'pal-stem-separator$'
    if _, err := exec.LookPath("pkill"); err == nil {
        _ = exec.Command("pkill", "-f", "pal-stem-separator$").Start()
    }
    // Also scan /proc and send SIGTERM to matching PIDs
    for _, pid := range findServicePIDs() {
        _ = syscall.Kill(pid, syscall.SIGTERM)
    }
}

func toInt(s string) int {
    n := 0
    for i := 0; i < len(s); i++ {
        c := s[i]
        if c < '0' || c > '9' { break }
        n = n*10 + int(c-'0')
    }
    return n
}

// Start child process with captured logs
func (m *model) startChild() tea.Cmd {
    if m.childCmd != nil { return nil }
    var cmd *exec.Cmd
    if m.serviceDebug {
        // Pass debug to service as a single quoted arg
        cmd = exec.Command("pulseaudio-lambda", "stem-separator --debug")
    } else {
        cmd = exec.Command("pulseaudio-lambda", "pal-stem-separator")
    }
    // Start in a new process group so we can signal the group and kill descendants
    cmd.SysProcAttr = &syscall.SysProcAttr{Setpgid: true}
    stdout, _ := cmd.StdoutPipe()
    stderr, _ := cmd.StderrPipe()
    if err := cmd.Start(); err != nil {
        return nil
    }
    m.childCmd = cmd
    // Record process group id
    if pgid, err := syscall.Getpgid(cmd.Process.Pid); err == nil { m.childPGID = pgid }
    // Enable logs by default when we manage the process
    m.logs = nil
    m.vp.SetContent("")
    m.showLogs = true
    m.followTail = true

    go func() {
        sc := bufio.NewScanner(stdout)
        for sc.Scan() { m.logCh <- sc.Text() }
    }()
    go func() {
        sc := bufio.NewScanner(stderr)
        for sc.Scan() { m.logCh <- sc.Text() }
    }()
    // Begin polling logs
    return m.scheduleLogPoll()
}

func (m *model) stopChild() {
    if m.childCmd == nil { return }
    // Send SIGTERM to the whole process group to ensure child and its descendants exit
    if m.childPGID != 0 {
        _ = syscall.Kill(-m.childPGID, syscall.SIGTERM)
    } else {
        _ = m.childCmd.Process.Signal(syscall.SIGTERM)
    }
    // Also proactively signal any matching service PIDs we find (belt and suspenders)
    for _, pid := range findServicePIDs() {
        _ = syscall.Kill(pid, syscall.SIGTERM)
    }
    m.childCmd = nil
    m.childPGID = 0
    m.showLogs = false
}
