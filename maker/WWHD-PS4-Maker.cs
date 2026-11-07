// WWHD-PS4 Maker: a Windows app that turns your own copy of The Legend of Zelda: The Wind Waker HD (Wii U) into your
// own PS4 package (.pkg for GoldHEN). It runs maker\wwhd_ps4_maker.py with the Python in its tools\ folder and shows
// its steps, progress and log; nothing to install. The layout follows SMW Maker (github.com/iHaiDeeZ/SMW, MIT).
// C# 5 / .NET Framework 4 (in every Windows 10 and 11): maker\build-exe.cmd builds it with Windows' own compiler.
using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

[assembly: System.Reflection.AssemblyTitle("WWHD-PS4 Maker")]
[assembly: System.Reflection.AssemblyProduct("WWHD-PS4 Maker")]

class Worker {
    public ConcurrentQueue<string> Lines = new ConcurrentQueue<string>();
    public volatile bool Running;
    public volatile int ExitCode;
    Process proc;

    public void Start(string file, string args, string cwd) {
        var psi = new ProcessStartInfo(file, args);
        psi.UseShellExecute = false;
        psi.RedirectStandardOutput = true;
        psi.RedirectStandardError = true;
        psi.CreateNoWindow = true;
        psi.WorkingDirectory = cwd;
        psi.StandardOutputEncoding = Encoding.UTF8;
        psi.StandardErrorEncoding = Encoding.UTF8;
        psi.EnvironmentVariables.Remove("PYTHONHOME");
        psi.EnvironmentVariables.Remove("PYTHONPATH");
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";
        psi.EnvironmentVariables["WWHD_LANG"] = System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName;
        psi.EnvironmentVariables["PYTHONUNBUFFERED"] = "1";
        proc = new Process();
        proc.StartInfo = psi;
        proc.EnableRaisingEvents = true;
        proc.OutputDataReceived += (s, e) => { if (e.Data != null) Lines.Enqueue(e.Data); };
        proc.ErrorDataReceived += (s, e) => { if (e.Data != null) Lines.Enqueue(e.Data); };
        proc.Exited += (s, e) => { proc.WaitForExit(); ExitCode = proc.ExitCode; Running = false; };
        Running = true;
        proc.Start();
        proc.BeginOutputReadLine();
        proc.BeginErrorReadLine();
    }

    // The pipeline and everything it started (the compilers, the extractor...).
    public void Cancel() {
        try {
            if (proc != null && !proc.HasExited) {
                var psi = new ProcessStartInfo("taskkill", "/T /F /PID " + proc.Id);
                psi.CreateNoWindow = true;
                psi.UseShellExecute = false;
                Process.Start(psi).WaitForExit(5000);
            }
        } catch {}
    }
}

class MakerForm : Form {
    // French when Windows is in French, English everywhere else.
    static readonly bool fr = System.Globalization.CultureInfo.CurrentUICulture.TwoLetterISOLanguageName == "fr";
    static string L(string french, string english) { return fr ? french : english; }
    readonly string root = Path.GetDirectoryName(System.Reflection.Assembly.GetExecutingAssembly().Location);
    readonly Dictionary<string, TextBox> rows = new Dictionary<string, TextBox>();
    readonly List<Control> inputs = new List<Control>();
    TextBox ftp, log;
    RadioButton inPkg, viaFtp;
    CheckBox fresh;
    Label stepLabel, detail;
    ProgressBar bar;
    Button start, cancel, uploadOnly;
    readonly Worker worker = new Worker();
    readonly Timer timer = new Timer();
    readonly string settings;

    public MakerForm() {
        settings = Path.Combine(root, "maker.ini");
        Text = L("WWHD-PS4 Maker - The Wind Waker HD pour PS4 (GoldHEN)", "WWHD-PS4 Maker - The Wind Waker HD for PS4 (GoldHEN)");
        Font = new Font("Segoe UI", 9f);
        ClientSize = new Size(760, 640);
        MinimumSize = new Size(700, 560);
        try { Icon = Icon.ExtractAssociatedIcon(System.Reflection.Assembly.GetExecutingAssembly().Location); } catch {}

        var intro = new Label();
        intro.Text = L("Crée ton propre paquet PS4 du jeu à partir de TON jeu Wii U (image .wud/.wux et ses clés, archive " +
                     "Cemu .wua, ou dossier extrait avec code, content et meta). Le paquet contient le jeu : ne le " +
                     "partage jamais.",
                     "Builds your own PS4 package of the game from YOUR Wii U game (.wud/.wux image and its keys, Cemu " +
                     ".wua archive, or an extracted folder with code, content and meta). The package contains the game: " +
                     "never share it.");
        intro.SetBounds(12, 10, 736, 36);
        intro.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(intro);

        int y = 52;
        AddRow("game", L("Jeu (image, archive ou dossier)", "Game (image, archive or folder)"), ref y, true, true);
        AddRow("disckey", L("Clé du disque (.key, facultatif)", "Disc key (.key, optional)"), ref y, true, false);
        AddRow("commonkey", L("Clé commune Wii U (common.key ou keys.txt)", "Wii U common key (common.key or keys.txt)"), ref y, true, false);
        AddRow("out", L("Dossier de sortie", "Output folder"), ref y, false, true);

        inPkg = new RadioButton();
        inPkg.Text = L("Fichiers du jeu dans le paquet (un seul .pkg, recommandé)", "Game files in the package (one .pkg, recommended)");
        inPkg.SetBounds(12, y, 400, 22);
        inPkg.Checked = true;
        viaFtp = new RadioButton();
        viaFtp.Text = L("Fichiers du jeu par FTP dans /data/WWHD/game", "Game files over FTP into /data/WWHD/game");
        viaFtp.SetBounds(420, y, 330, 22);
        Controls.Add(inPkg);
        Controls.Add(viaFtp);
        inputs.Add(inPkg);
        inputs.Add(viaFtp);
        y += 28;

        var fl = new Label();
        fl.Text = L("FTP de la PS4 (GoldHEN, facultatif)", "PS4 FTP (GoldHEN, optional)");
        fl.SetBounds(12, y + 3, 220, 20);
        Controls.Add(fl);
        ftp = new TextBox();
        ftp.SetBounds(236, y, 200, 23);
        Controls.Add(ftp);
        inputs.Add(ftp);
        var fh = new Label();
        fh.Text = L("ex. 192.168.1.20:2121", "e.g. 192.168.1.20:2121");
        fh.ForeColor = Color.Gray;
        fh.SetBounds(444, y + 3, 200, 20);
        Controls.Add(fh);
        y += 34;

        start = new Button();
        start.Text = L("Démarrer", "Start");
        start.SetBounds(12, y, 120, 30);
        start.Click += (s, e) => Run(false);
        uploadOnly = new Button();
        uploadOnly.Text = L("Envoyer seulement", "Upload only");
        uploadOnly.SetBounds(140, y, 140, 30);
        uploadOnly.Click += (s, e) => Run(true);
        cancel = new Button();
        cancel.Text = L("Annuler", "Cancel");
        cancel.SetBounds(288, y, 100, 30);
        cancel.Enabled = false;
        cancel.Click += (s, e) => { worker.Cancel(); Append(L("annulé", "cancelled")); };
        Controls.Add(start);
        Controls.Add(uploadOnly);
        Controls.Add(cancel);
        fresh = new CheckBox();
        fresh.Text = L("Tout recommencer (sinon le travail déjà fait est repris)", "Start over (otherwise the work already done is reused)");
        fresh.SetBounds(400, y + 5, 350, 22);
        Controls.Add(fresh);
        inputs.Add(fresh);
        y += 40;

        stepLabel = new Label();
        stepLabel.Font = new Font(Font, FontStyle.Bold);
        stepLabel.SetBounds(12, y, 736, 20);
        stepLabel.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(stepLabel);
        y += 22;
        bar = new ProgressBar();
        bar.SetBounds(12, y, 736, 18);
        bar.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(bar);
        y += 22;
        detail = new Label();
        detail.ForeColor = Color.Gray;
        detail.SetBounds(12, y, 736, 18);
        detail.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(detail);
        y += 22;

        log = new TextBox();
        log.Multiline = true;
        log.ReadOnly = true;
        log.ScrollBars = ScrollBars.Both;
        log.WordWrap = false;
        log.Font = new Font("Consolas", 8.5f);
        log.SetBounds(12, y, 736, ClientSize.Height - y - 12);
        log.Anchor = AnchorStyles.Top | AnchorStyles.Bottom | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(log);

        LoadSettings();
        if (rows["out"].Text.Length == 0) rows["out"].Text = Path.Combine(root, "sortie");
        timer.Interval = 100;
        timer.Tick += (s, e) => Pump();
        timer.Start();
        FormClosing += (s, e) => {
            if (worker.Running && MessageBox.Show(this, L("Le travail en cours sera arrêté. Fermer quand même ?", "The work in progress will be stopped. Close anyway?"),
                    Text, MessageBoxButtons.YesNo, MessageBoxIcon.Question) != DialogResult.Yes) {
                e.Cancel = true;
                return;
            }
            worker.Cancel();
            SaveSettings();
        };
    }

    void AddRow(string key, string label, ref int y, bool file, bool folder) {
        var l = new Label();
        l.Text = label;
        l.SetBounds(12, y + 3, 250, 20);
        Controls.Add(l);
        var t = new TextBox();
        t.SetBounds(266, y, folder && file ? 330 : 400, 23);
        t.Anchor = AnchorStyles.Top | AnchorStyles.Left | AnchorStyles.Right;
        Controls.Add(t);
        rows[key] = t;
        inputs.Add(t);
        int x = folder && file ? 602 : 672;
        if (file) {
            var b = new Button();
            b.Text = L("Fichier...", "File...");
            b.SetBounds(x, y - 1, 70, 25);
            b.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            b.Click += (s, e) => PickFile(key);
            Controls.Add(b);
            inputs.Add(b);
            x += 74;
        }
        if (folder) {
            var b = new Button();
            b.Text = L("Dossier...", "Folder...");
            b.SetBounds(x, y - 1, 70, 25);
            b.Anchor = AnchorStyles.Top | AnchorStyles.Right;
            b.Click += (s, e) => PickFolder(key);
            Controls.Add(b);
            inputs.Add(b);
        }
        y += 30;
    }

    void PickFile(string key) {
        var d = new OpenFileDialog();
        d.Filter = key == "game" ? L("Jeu Wii U (*.wud;*.wux;*.wua)|*.wud;*.wux;*.wua|Tous les fichiers|*.*", "Wii U game (*.wud;*.wux;*.wua)|*.wud;*.wux;*.wua|All files|*.*")
                                 : L("Clés (*.key;*.txt;*.bin)|*.key;*.txt;*.bin|Tous les fichiers|*.*", "Keys (*.key;*.txt;*.bin)|*.key;*.txt;*.bin|All files|*.*");
        if (d.ShowDialog(this) != DialogResult.OK) return;
        rows[key].Text = d.FileName;
        if (key == "game") GuessKeys(d.FileName);
    }

    void PickFolder(string key) {
        var d = new FolderBrowserDialog();
        d.Description = key == "game" ? L("Le dossier du jeu extrait (avec code, content et meta)", "The extracted game folder (with code, content and meta)") : L("Le dossier de sortie", "The output folder");
        if (d.ShowDialog(this) == DialogResult.OK) rows[key].Text = d.SelectedPath;
    }

    // keys next to the image, as the PC version's setup finds them
    void GuessKeys(string image) {
        string dir = Path.GetDirectoryName(image);
        string disc = Path.ChangeExtension(image, ".key");
        if (rows["disckey"].Text.Length == 0 && File.Exists(disc)) rows["disckey"].Text = disc;
        foreach (string n in new string[] { "common.key", "keys.txt" }) {
            string c = Path.Combine(dir, n);
            if (rows["commonkey"].Text.Length == 0 && File.Exists(c)) rows["commonkey"].Text = c;
        }
    }

    static string Q(string s) { return "\"" + s.Replace("\"", "\\\"") + "\""; }

    void Run(bool uploadOnlyMode) {
        string python = Path.Combine(root, "tools", "python", "python.exe");
        string script = Path.Combine(root, "maker", "wwhd_ps4_maker.py");
        if (!File.Exists(python) || !File.Exists(script)) {
            MessageBox.Show(this, L("tools\\python\\python.exe ou maker\\wwhd_ps4_maker.py manque : décompresse le Maker à nouveau.", "tools\\python\\python.exe or maker\\wwhd_ps4_maker.py is missing: unpack the Maker again."),
                            Text, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        string outDir = rows["out"].Text.Trim();
        if (outDir.Length == 0) { MessageBox.Show(this, L("Choisis un dossier de sortie.", "Choose an output folder."), Text); return; }
        var a = new StringBuilder("-u " + Q(script) + " --out " + Q(outDir));
        if (uploadOnlyMode) {
            if (ftp.Text.Trim().Length == 0) { MessageBox.Show(this, L("Indique l'adresse FTP de la PS4.", "Enter the PS4's FTP address."), Text); return; }
            a.Append(" --upload-only");
        } else {
            string game = rows["game"].Text.Trim();
            if (game.Length == 0) { MessageBox.Show(this, L("Choisis ton jeu (image, archive ou dossier).", "Choose your game (image, archive or folder)."), Text); return; }
            a.Append(" --game " + Q(game));
            if (rows["disckey"].Text.Trim().Length > 0) a.Append(" --disc-key " + Q(rows["disckey"].Text.Trim()));
            if (rows["commonkey"].Text.Trim().Length > 0) a.Append(" --common-key " + Q(rows["commonkey"].Text.Trim()));
        }
        a.Append(" --data " + (viaFtp.Checked ? "ftp" : "in-pkg"));
        if (ftp.Text.Trim().Length > 0) a.Append(" --ftp " + ftp.Text.Trim());
        if (fresh.Checked && !uploadOnlyMode) a.Append(" --fresh");
        SaveSettings();
        log.Clear();
        bar.Value = 0;
        stepLabel.Text = "";
        detail.Text = "";
        SetBusy(true);
        worker.Start(python, a.ToString(), root);
    }

    void SetBusy(bool busy) {
        foreach (var c in inputs) c.Enabled = !busy;
        start.Enabled = uploadOnly.Enabled = !busy;
        cancel.Enabled = busy;
    }

    void Append(string line) {
        log.AppendText(line + Environment.NewLine);
        if (log.TextLength > 2000000) log.Text = log.Text.Substring(log.TextLength - 1000000);
    }

    static readonly Regex StepRe = new Regex(@"^== (\d+)/(\d+) (.*)$");
    static readonly Regex ProgRe = new Regex(@"^progress (\d+) (\d+) ?(.*)$");
    static readonly Regex StatusRe = new Regex(@"^status ?(.*)$");

    void Marquee(bool on) {
        ProgressBarStyle want = on ? ProgressBarStyle.Marquee : ProgressBarStyle.Blocks;
        if (bar.Style != want) bar.Style = want;
        if (on) bar.MarqueeAnimationSpeed = 30;
    }

    void Pump() {
        string line;
        int n = 0;
        while (n++ < 400 && worker.Lines.TryDequeue(out line)) {
            Match m = StepRe.Match(line);
            if (m.Success) {
                stepLabel.Text = L("Étape ", "Step ") + m.Groups[1].Value + L(" sur ", " of ") + m.Groups[2].Value + " : " + m.Groups[3].Value;
                Marquee(false);
                bar.Value = 0;
                detail.Text = "";
                Append(line);
                continue;
            }
            m = ProgRe.Match(line);
            if (m.Success) {
                Marquee(false);
                long done = long.Parse(m.Groups[1].Value), total = Math.Max(1, long.Parse(m.Groups[2].Value));
                bar.Value = (int)Math.Min(100, done * 100 / total);
                detail.Text = m.Groups[3].Value + " (" + bar.Value + " %)";
                continue;
            }
            m = StatusRe.Match(line);
            if (m.Success) {  // silent work: a moving bar and the elapsed time, so it does not look frozen
                string t = m.Groups[1].Value;
                Marquee(t.Length > 0);
                if (t.Length > 0) detail.Text = t;
                continue;
            }
            Append(line);
        }
        if (!worker.Running && cancel.Enabled && worker.Lines.IsEmpty) {
            SetBusy(false);
            Marquee(false);
            if (worker.ExitCode == 0) {
                bar.Value = 100;
                stepLabel.Text = L("Terminé", "Done");
                detail.Text = L("Installe le .pkg avec le Package Installer de GoldHEN.", "Install the .pkg with GoldHEN's Package Installer.");
            } else {
                stepLabel.Text = L("Arrêté (voir le journal)", "Stopped (see the log)");
            }
        }
    }

    void LoadSettings() {
        if (!File.Exists(settings)) return;
        foreach (string l in File.ReadAllLines(settings, Encoding.UTF8)) {
            int eq = l.IndexOf('=');
            if (eq <= 0) continue;
            string k = l.Substring(0, eq), v = l.Substring(eq + 1);
            if (rows.ContainsKey(k)) rows[k].Text = v;
            else if (k == "ftp") ftp.Text = v;
            else if (k == "data") viaFtp.Checked = !(inPkg.Checked = v != "ftp");
        }
    }

    void SaveSettings() {
        try {
            var sb = new StringBuilder();
            foreach (var kv in rows) sb.AppendLine(kv.Key + "=" + kv.Value.Text.Trim());
            sb.AppendLine("ftp=" + ftp.Text.Trim());
            sb.AppendLine("data=" + (viaFtp.Checked ? "ftp" : "in-pkg"));
            File.WriteAllText(settings, sb.ToString(), Encoding.UTF8);
        } catch {}
    }

    [STAThread]
    static void Main() {
        Application.EnableVisualStyles();
        Application.SetCompatibleTextRenderingDefault(false);
        Application.Run(new MakerForm());
    }
}
