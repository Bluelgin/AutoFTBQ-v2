package dev.autoftbq.agent.client;

import java.awt.BasicStroke;
import java.awt.Color;
import java.awt.Font;
import java.awt.RenderingHints;
import java.awt.image.BufferedImage;
import java.io.ByteArrayOutputStream;
import java.util.ArrayList;
import java.util.Base64;
import java.util.List;
import javax.imageio.ImageIO;

/** Raw freehand ink, not semantic task nodes. Coordinates are fixed paper pixels. */
public final class SketchDocument {
    public static final int WIDTH = 1024, HEIGHT = 640;
    public record Point(double x, double y) { }
    public record Mark(List<Point> points, int color, int width, String text, boolean clear) { }
    private final List<Mark> marks = new ArrayList<>(), redo = new ArrayList<>();
    public List<Mark> marks() { return List.copyOf(marks); }
    public void add(Mark mark) {
        if (marks.size() >= 500) throw new IllegalStateException("草图笔画过多，请先撤销部分笔画");
        if (marks.stream().mapToInt(m -> m.points().size()).sum() + mark.points().size() > 30000)
            throw new IllegalStateException("草图过于复杂，请撤销部分笔画");
        marks.add(new Mark(List.copyOf(mark.points()), mark.color(), mark.width(), mark.text(), mark.clear()));
        redo.clear();
    }
    public void undo() { if (!marks.isEmpty()) redo.add(marks.remove(marks.size() - 1)); }
    public void redo() { if (!redo.isEmpty()) marks.add(redo.remove(redo.size() - 1)); }
    public void clear() { add(new Mark(List.of(), 0, 0, "", true)); }
    public boolean hasInk() {
        for (int i = marks.size() - 1; i >= 0; i--) {
            Mark m = marks.get(i);
            if (m.clear()) return false;
            if (m.color() != 0xFFFFFFFF && !m.points().isEmpty()) return true;
        }
        return false;
    }
    public String pngDataUrl() throws Exception {
        BufferedImage image = new BufferedImage(WIDTH, HEIGHT, BufferedImage.TYPE_INT_RGB);
        var g = image.createGraphics();
        try {
            g.setColor(Color.WHITE); g.fillRect(0, 0, WIDTH, HEIGHT);
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING, RenderingHints.VALUE_ANTIALIAS_ON);
            for (Mark mark : marks) {
                if (mark.clear()) { g.setColor(Color.WHITE); g.fillRect(0, 0, WIDTH, HEIGHT); continue; }
                g.setColor(new Color(mark.color(), true));
                if (!mark.text().isEmpty()) {
                    g.setFont(new Font("Microsoft YaHei", Font.PLAIN, 22));
                    Point p = mark.points().get(0);
                    g.drawString(mark.text(), (float)p.x(), (float)p.y() + 22);
                } else {
                    g.setStroke(new BasicStroke(mark.width(), BasicStroke.CAP_ROUND, BasicStroke.JOIN_ROUND));
                    for (int i = 0; i < mark.points().size(); i++) {
                        Point a = mark.points().get(Math.max(0, i - 1)), b = mark.points().get(i);
                        g.drawLine((int)a.x(), (int)a.y(), (int)b.x(), (int)b.y());
                    }
                }
            }
        } finally { g.dispose(); }
        ByteArrayOutputStream bytes = new ByteArrayOutputStream();
        ImageIO.write(image, "PNG", bytes);
        return "data:image/png;base64," + Base64.getEncoder().encodeToString(bytes.toByteArray());
    }
}
