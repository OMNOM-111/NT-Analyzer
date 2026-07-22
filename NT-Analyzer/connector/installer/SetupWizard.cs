using System;
using System.Drawing;
using System.Linq;
using System.Windows.Forms;

using Newtonsoft.Json.Linq;

namespace StratForge.Connector.Setup
{
    internal sealed class SetupWizard : Form
    {
        private readonly VerifiedRelease _release;
        private readonly TextBox _ninjaDir = new TextBox();
        private readonly TextBox _origin = new TextBox();
        private readonly TextBox _code = new TextBox();
        private readonly ComboBox _channel = new ComboBox();
        private readonly ComboBox _policy = new ComboBox();
        private readonly Label _status = new Label();

        public SetupWizard(VerifiedRelease release, InstallOptions defaults)
        {
            _release = release;
            Text = "StratForge Connector " + release.Version;
            Width = 680;
            Height = 500;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            Font = new Font("Segoe UI", 9F);

            Label title = new Label
            {
                Text = "Подключение NinjaTrader к StratForge",
                Font = new Font("Segoe UI Semibold", 15F),
                AutoSize = true,
                Left = 24,
                Top = 20,
            };
            Controls.Add(title);
            Controls.Add(NewLabel(
                "Установщик проверяет подпись и хэши пакета, сохраняет rollback и не запрашивает данные брокера.",
                24, 58, 620));

            AddField("Каталог пользователя NinjaTrader 8", _ninjaDir, 98);
            _ninjaDir.Text = defaults.NinjaUserDir ??
                InstallerEngine.DetectNinjaUserDirs().FirstOrDefault() ?? "";
            Button browse = new Button { Text = "Выбрать…", Left = 540, Top = 119, Width = 95 };
            browse.Click += delegate
            {
                using (FolderBrowserDialog dialog = new FolderBrowserDialog())
                {
                    dialog.Description = "Выберите каталог NinjaTrader 8";
                    dialog.SelectedPath = _ninjaDir.Text;
                    if (dialog.ShowDialog(this) == DialogResult.OK) _ninjaDir.Text = dialog.SelectedPath;
                }
            };
            _ninjaDir.Width = 500;
            Controls.Add(browse);

            AddField("StratForge server", _origin, 157);
            _origin.Text = defaults.ServerOrigin;
            AddField("Одноразовый код подключения", _code, 216);
            _code.UseSystemPasswordChar = true;
            _code.Text = defaults.EnrollmentCode ?? "";

            Controls.Add(NewLabel("Канал", 24, 276, 100));
            _channel.SetBounds(24, 296, 180, 28);
            _channel.DropDownStyle = ComboBoxStyle.DropDownList;
            _channel.Items.AddRange(new object[] { "stable", "canary" });
            _channel.SelectedItem = defaults.Channel == "canary" ? "canary" : "stable";
            Controls.Add(_channel);
            Controls.Add(NewLabel("Политика обновления", 224, 276, 200));
            _policy.SetBounds(224, 296, 200, 28);
            _policy.DropDownStyle = ComboBoxStyle.DropDownList;
            _policy.Items.AddRange(new object[] { "safe_restart", "manual" });
            _policy.SelectedItem = defaults.UpdatePolicy == "manual" ? "manual" : "safe_restart";
            Controls.Add(_policy);

            Button install = ActionButton("Установить", 24, false, false);
            Button repair = ActionButton("Восстановить", 154, true, false);
            Button uninstall = ActionButton("Удалить", 304, false, true);
            Button close = new Button { Text = "Закрыть", Left = 510, Top = 352, Width = 125 };
            close.Click += delegate { Close(); };
            Controls.Add(install);
            Controls.Add(repair);
            Controls.Add(uninstall);
            Controls.Add(close);

            _status.SetBounds(24, 400, 610, 44);
            _status.Text = "Пакет проверен. NinjaTrader должен быть закрыт перед изменением файлов.";
            _status.ForeColor = Color.DimGray;
            Controls.Add(_status);
        }

        private Button ActionButton(string text, int left, bool repair, bool uninstall)
        {
            Button button = new Button { Text = text, Left = left, Top = 352, Width = 120 };
            button.Click += delegate
            {
                if (uninstall && MessageBox.Show(
                    this,
                    "Удалить Connector и восстановить файлы, существовавшие до установки? Локальные ключи и backup будут сохранены.",
                    "StratForge Connector",
                    MessageBoxButtons.YesNo,
                    MessageBoxIcon.Warning) != DialogResult.Yes) return;
                RunAction(button, repair, uninstall);
            };
            Controls.Add(button);
            return button;
        }

        private void RunAction(Button button, bool repair, bool uninstall)
        {
            button.Enabled = false;
            _status.ForeColor = Color.DimGray;
            _status.Text = "Проверка и выполнение…";
            try
            {
                InstallOptions options = new InstallOptions
                {
                    NinjaUserDir = _ninjaDir.Text,
                    ServerOrigin = _origin.Text,
                    EnrollmentCode = _code.Text,
                    Channel = (string)_channel.SelectedItem ?? "stable",
                    UpdatePolicy = (string)_policy.SelectedItem ?? "safe_restart",
                };
                JObject result = uninstall
                    ? InstallerEngine.Uninstall(_release, options)
                    : InstallerEngine.InstallOrRepair(_release, options, repair);
                _code.Clear();
                _status.ForeColor = Color.DarkGreen;
                _status.Text = uninstall
                    ? "Удаление завершено; исходные файлы восстановлены."
                    : "Готово. Запустите NinjaTrader и проверьте статус Connector в StratForge.";
                MessageBox.Show(this, _status.Text, "StratForge Connector", MessageBoxButtons.OK,
                    MessageBoxIcon.Information);
            }
            catch (Exception exc)
            {
                _status.ForeColor = Color.DarkRed;
                _status.Text = exc.Message;
                MessageBox.Show(this, exc.Message, "StratForge Connector", MessageBoxButtons.OK,
                    MessageBoxIcon.Error);
            }
            finally
            {
                button.Enabled = true;
            }
        }

        private void AddField(string label, TextBox box, int top)
        {
            Controls.Add(NewLabel(label, 24, top, 610));
            box.SetBounds(24, top + 21, 610, 28);
            Controls.Add(box);
        }

        private static Label NewLabel(string text, int left, int top, int width)
        {
            return new Label { Text = text, Left = left, Top = top, Width = width, AutoSize = false };
        }
    }
}
