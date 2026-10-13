using Forms = System.Windows.Forms;

namespace QingGuiAI.Cad;

// AutoCAD can restore a dock width smaller than the requested initial palette size.
// Keep all children inside the actual client area; only vertical scrolling is useful.
internal sealed class ResponsivePalettePanel : Forms.FlowLayoutPanel
{
    private bool fitting;

    protected override void OnClientSizeChanged(EventArgs e)
    {
        base.OnClientSizeChanged(e);
        FitChildren();
    }

    protected override void OnControlAdded(Forms.ControlEventArgs e)
    {
        base.OnControlAdded(e);
        FitChildren();
    }

    private void FitChildren()
    {
        if (fitting || ClientSize.Width <= 0) return;
        fitting = true;
        SuspendLayout();
        try
        {
            // Reserve the scrollbar even before it appears, preventing width/height oscillation.
            int available = Math.Max(1, ClientSize.Width - Padding.Horizontal - Forms.SystemInformation.VerticalScrollBarWidth - 2);
            foreach (Forms.Control child in Controls)
            {
                int width = Math.Max(1, available - child.Margin.Horizontal);
                if (child is Forms.Label label)
                {
                    label.MaximumSize = new System.Drawing.Size(width, 0);
                }
                else if (child is Forms.Button button)
                {
                    button.Width = width;
                    int textWidth = Math.Max(1, width - button.Padding.Horizontal - 6);
                    var textSize = Forms.TextRenderer.MeasureText(button.Text, button.Font,
                        new System.Drawing.Size(textWidth, int.MaxValue), Forms.TextFormatFlags.WordBreak | Forms.TextFormatFlags.TextBoxControl | Forms.TextFormatFlags.NoPrefix);
                    button.Height = Math.Max(44, textSize.Height + button.Padding.Vertical + 10);
                }
                else child.Width = width;
            }
            AutoScrollMinSize = System.Drawing.Size.Empty;
            HorizontalScroll.Maximum = 0;
            HorizontalScroll.Enabled = false;
            HorizontalScroll.Visible = false;
        }
        finally
        {
            ResumeLayout(true);
            fitting = false;
        }
    }
}
