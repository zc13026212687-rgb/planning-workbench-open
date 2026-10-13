param([string]$OutputPath=(Join-Path $PSScriptRoot 'QingGuiAI.ico'))
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Drawing
$frames = foreach($size in @(16,32,48,64,256)) {
    $bitmap=[Drawing.Bitmap]::new($size,$size)
    $graphics=[Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode=[Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.Clear([Drawing.Color]::Transparent)
    $scale=$size/256.0
    $graphics.ScaleTransform($scale,$scale)
    $shape=[Drawing.Drawing2D.GraphicsPath]::new()
    $shape.AddArc(10,10,56,56,180,90); $shape.AddArc(190,10,56,56,270,90)
    $shape.AddArc(190,190,56,56,0,90); $shape.AddArc(10,190,56,56,90,90); $shape.CloseFigure()
    $background=[Drawing.SolidBrush]::new([Drawing.Color]::FromArgb(255,14,51,72))
    $graphics.FillPath($background,$shape)
    $grid=[Drawing.Pen]::new([Drawing.Color]::FromArgb(255,44,104,120),5)
    foreach($axis in @(65,128,191)) { $graphics.DrawLine($grid,$axis,40,$axis,216); $graphics.DrawLine($grid,40,$axis,216,$axis) }
    $outline=[Drawing.Pen]::new([Drawing.Color]::FromArgb(255,235,249,250),30)
    $route=[Drawing.Pen]::new([Drawing.Color]::FromArgb(255,61,219,188),18)
    $outline.StartCap=[Drawing.Drawing2D.LineCap]::Round; $outline.EndCap=[Drawing.Drawing2D.LineCap]::Round
    $route.StartCap=[Drawing.Drawing2D.LineCap]::Round; $route.EndCap=[Drawing.Drawing2D.LineCap]::Round
    $points=[Drawing.PointF[]]@([Drawing.PointF]::new(57,191),[Drawing.PointF]::new(104,142),[Drawing.PointF]::new(153,142),[Drawing.PointF]::new(202,65))
    $graphics.DrawLines($outline,$points); $graphics.DrawLines($route,$points)
    $stream=[IO.MemoryStream]::new(); $bitmap.Save($stream,[Drawing.Imaging.ImageFormat]::Png)
    $frame=[pscustomobject]@{Size=$size;Bytes=$stream.ToArray()}
    $stream.Dispose(); $route.Dispose(); $outline.Dispose(); $grid.Dispose(); $background.Dispose(); $shape.Dispose(); $graphics.Dispose(); $bitmap.Dispose()
    $frame
}
$output=[IO.File]::Create([IO.Path]::GetFullPath($OutputPath)); $writer=[IO.BinaryWriter]::new($output)
try {
    $writer.Write([uint16]0); $writer.Write([uint16]1); $writer.Write([uint16]$frames.Count)
    $offset=6+16*$frames.Count
    foreach($frame in $frames) {
        $dimension=if($frame.Size -eq 256){0}else{$frame.Size}
        $writer.Write([byte]$dimension); $writer.Write([byte]$dimension); $writer.Write([byte]0); $writer.Write([byte]0)
        $writer.Write([uint16]1); $writer.Write([uint16]32); $writer.Write([uint32]$frame.Bytes.Length); $writer.Write([uint32]$offset)
        $offset+=$frame.Bytes.Length
    }
    foreach($frame in $frames) { $writer.Write([byte[]]$frame.Bytes) }
} finally { $writer.Dispose(); $output.Dispose() }
