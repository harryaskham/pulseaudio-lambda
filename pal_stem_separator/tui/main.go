package main

import (
    "encoding/json"
    "errors"
    "fmt"
    tea "github.com/charmbracelet/bubbletea"
    "github.com/charmbracelet/bubbles/textinput"
    "github.com/charmbracelet/lipgloss"
    "io/fs"
    "math"
    "os"
    "path/filepath"
    "strings"
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
    inKBps      float64
    outKBps     float64
    rtf         float64 // processed seconds per wall second
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
)

func (m model) Init() tea.Cmd {
    return tea.Tick(1*time.Second, func(time.Time) tea.Msg { return msgStatsTick{} })
}

func (m *model) scheduleSave() tea.Cmd {
    if m.pendingSave { return nil }
    m.pendingSave = true
    return tea.Tick(200*time.Millisecond, func(time.Time) tea.Msg { return msgSave{} })
}

func (m *model) scheduleStats() tea.Cmd {
    return tea.Tick(1*time.Second, func(time.Time) tea.Msg { return msgStatsTick{} })
}

func (m model) Update(msg tea.Msg) (tea.Model, tea.Cmd) {
    switch msg := msg.(type) {
    case tea.KeyMsg:
        switch msg.String() {
        case "ctrl+c", "q":
            return m, tea.Quit
        case "up":
            if m.focused > 0 { m.focused-- }
        case "down":
            m.focused++
            if m.focused > 19 { m.focused = 19 }
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
            }
        // no explicit save button/hotkey; autosave is default
        case "r": m.cfg.ResetVolumes(); for i:=0;i<4;i++{ m.gain[i].Value = 100 }; return m, m.scheduleSave()
        case "e": m.cfg.RequestEmptyQueues(); return m, m.scheduleSave()
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
        if !m.lastStatsAt.IsZero() {
            dt := now.Sub(m.lastStatsAt).Seconds()
            if dt > 0 {
                m.inKBps = maxf((s.InputBytes-m.prevStats.InputBytes)/dt/1024.0, 0)
                m.outKBps = maxf((s.OutputBytes-m.prevStats.OutputBytes)/dt/1024.0, 0)
                m.rtf = maxf((s.ProcessedSecs-m.prevStats.ProcessedSecs)/dt, 0)
            }
        }
        m.prevStats = m.stats
        m.stats = s
        m.lastStatsAt = now
        return m, m.scheduleStats()
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

func (m model) View() string {
    w := max(60, m.width-6) // leave some room for panel padding
    b := &strings.Builder{}
    fmt.Fprintln(b, titleStyle.Render("paλ-stem-separator"))

    // Live Stats
    sb := &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Live Stats"))
    // Latency bar (target 45s scale) with chunk marker
    latency := m.stats.LatencySecs
    fmt.Fprintln(sb, "  Latency:")
    fmt.Fprintln(sb, "   "+renderBarWithMarker(latency/45.0, w-6, latencyLabel(latency), latencyColor(latency), m.cfg.ChunkSecs/45.0))
    // Throughput and speed
    fmt.Fprintf(sb, "  %s    %s    RTF: %.2fx\n", formatRate("In", m.inKBps*1024), formatRate("Out", m.outKBps*1024), m.rtf)
    // Raw totals
    fmt.Fprintf(sb, "  Input:     %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.InputBytes), formatInt(m.stats.InputSamples), m.stats.InputSecs)
    fmt.Fprintf(sb, "  Processed: %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.ProcessedBytes), formatInt(m.stats.ProcessedSamples), m.stats.ProcessedSecs)
    fmt.Fprintf(sb, "  Output:    %8s  %12s samples  %6.2f s\n", formatBytes(m.stats.OutputBytes), formatInt(m.stats.OutputSamples), m.stats.OutputSecs)
    fmt.Fprintln(b, panelStyle.Render(sb.String()))

    // Volume Controls
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Stem Volumes"))
    for i := 0; i < 4; i++ {
        volIdx := 3*i + 0
        muteIdx := 3*i + 1
        soloIdx := 3*i + 2
        line := m.gain[i].Render(w)
        if m.focused == volIdx { line = focusStyle.Render(line) }
        fmt.Fprintln(sb, " "+line)
        // mute / solo as single-line toggles
        mute := renderToggle("Mute", m.cfg.Muted[i], m.focused == muteIdx, nord11, nord4)
        solo := renderToggle("Solo", m.cfg.Soloed[i], m.focused == soloIdx, nord13, nord4)
        btns := lipgloss.JoinHorizontal(lipgloss.Top, mute, "  ", solo)
        fmt.Fprintln(sb, "   "+btns)
    }
    // Reset (placed immediately after volumes)
    reset := btnStyle.Render("Reset All Volumes")
    if m.focused == 12 { reset = focusStyle.Render(reset) }
    fmt.Fprintln(sb, "  "+reset)
    fmt.Fprintln(b, panelStyle.Render(sb.String()))

    // Processing settings
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Processing Settings"))
    line := m.chunk.Render(w); if m.focused==13 { line = focusStyle.Render(line) }; fmt.Fprintln(sb, " "+line)
    line = m.overlap.Render(w); if m.focused==14 { line = focusStyle.Render(line) }; fmt.Fprintln(sb, " "+line)
    // Device
    cpu := renderRadio("CPU", m.cfg.Device=="cpu", m.focused==15)
    cuda := renderRadio("CUDA", m.cfg.Device=="cuda", m.focused==16)
    deviceBtns := lipgloss.JoinHorizontal(lipgloss.Top, cpu, "  ", cuda)
    fmt.Fprintln(sb, "  Device: "+deviceBtns)
    // Normalize
    norm := renderToggle("Normalize", m.cfg.Normalize, m.focused==17, nord14, nord4)
    fmt.Fprintln(sb, "  "+norm)
    // Empty queues
    empty := btnStyle.Render("Empty Queues"); if m.focused==18 { empty = focusStyle.Render(empty) }
    fmt.Fprintln(sb, "  "+empty)
    fmt.Fprintln(b, panelStyle.Render(sb.String()))

    // Checkpoint
    sb = &strings.Builder{}
    fmt.Fprintln(sb, sectionStyle.Render("Model Checkpoint"))
    ti := m.chkpt.View(); if m.focused==19 { ti = focusStyle.Render(ti) }
    fmt.Fprintln(sb, "  "+ti)
    fmt.Fprintln(b, panelStyle.Render(sb.String()))

    // Help
    fmt.Fprintln(b, "")
    fmt.Fprintln(b, lipgloss.NewStyle().Faint(true).Render("↑/↓ navigate  ←/→ adjust  Enter toggle  r reset  e empty  q quit"))
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
    out := fmt.Sprintf("%s %s", box, label)
    if focused { out = focusStyle.Render(out) }
    return style.Render(out)
}

// Single-line radio ( ) Label or (•) Label
func renderRadio(label string, selected bool, focused bool) string {
    dot := "( )"
    style := lipgloss.NewStyle().Foreground(nord4)
    if selected { dot = "(•)"; style = style.Copy().Foreground(nord10) }
    out := fmt.Sprintf("%s %s", dot, label)
    if focused { out = focusStyle.Render(out) }
    return style.Render(out)
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
    return style.Render(fmt.Sprintf("[%s] %s", string(barRunes), label))
}

func latencyLabel(s float64) string { return fmt.Sprintf("%.2f s", s) }
func latencyColor(s float64) lipgloss.Color {
    if s >= 45.0 { return nord11 } // red at/exceed max window
    if s >= 40.0 { return nord13 } // amber when approaching end
    return nord14                 // green
}
func maxf(a, b float64) float64 { if a>b {return a}; return b }

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
    m := initialModel()
    // Kick off stats polling immediately and enable mouse tracking
    p := tea.NewProgram(m, tea.WithAltScreen(), tea.WithMouseCellMotion())
    if _, err := p.Run(); err != nil {
        fmt.Fprintf(os.Stderr, "error: %v\n", err)
        os.Exit(1)
    }
}
