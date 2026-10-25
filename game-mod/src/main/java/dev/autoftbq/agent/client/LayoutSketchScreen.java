package dev.autoftbq.agent.client;

import dev.autoftbq.agent.bridge.BridgeClient;
import net.minecraft.client.gui.GuiGraphics;
import net.minecraft.client.gui.components.Button;
import net.minecraft.client.gui.components.EditBox;
import net.minecraft.client.gui.screens.Screen;
import net.minecraft.network.chat.Component;

import java.util.ArrayList;
import java.util.List;

/** Full-screen freehand input. The exact exported paper is sent to the vision model. */
public final class LayoutSketchScreen extends Screen {
    private static final SketchDocument DOCUMENT = new SketchDocument();
    private static String savedPrompt = "", savedLabel = "";
    private static boolean nodes;
    private final Screen parent;
    private EditBox prompt, label;
    private String tool = "pen";
    private String message = tr("screen.autoftbq_agent.sketch_help");
    private int color = 0xFF202020;
    private double zoom = 1, panX, panY;
    private final List<SketchDocument.Point> stroke = new ArrayList<>();
    private boolean dragging, panning, preview, extraTools;
    private Button send;
    private net.minecraft.resources.ResourceLocation previewTexture;

    public LayoutSketchScreen(Screen parent) {
        super(Component.translatable("screen.autoftbq_agent.sketch_title"));
        this.parent = parent;
    }

    private static String tr(String key, Object... args) {
        return Component.translatable(key, args).getString();
    }

    private Button button(int x, int y, int w, String title, Runnable action) {
        return addRenderableWidget(Button.builder(Component.literal(title), b -> {
            if (y == 20 || y == 44) preview = false;
            action.run();
        }).bounds(x, y, w, 20).build());
    }

    @Override
    protected void init() {
        int x = 8;
        int tw = Math.min(58, Math.max(40, (width - 28) / 6));
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_pen"), () -> tool = "pen");
        x += tw + 2;
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_eraser"), () -> tool = "erase");
        x += tw + 2;
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_text"), () -> tool = "text");
        x += tw + 2;
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_undo"), DOCUMENT::undo);
        x += tw + 2;
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_redo"), DOCUMENT::redo);
        x += tw + 2;
        button(x, 20, tw, tr("screen.autoftbq_agent.sketch_more"), this::toggleExtraTools);

        if (extraTools) {
            int ex = 8;
            int ew = Math.min(92, Math.max(60, (width - 20) / 3));
            button(ex, 44, ew, tr("screen.autoftbq_agent.sketch_clear"), () -> {
                try {
                    DOCUMENT.clear();
                } catch (Exception error) {
                    message = error.getMessage();
                }
            });
            ex += ew + 2;
            button(ex, 44, ew, tr("screen.autoftbq_agent.sketch_fit"), () -> {
                zoom = 1;
                panX = panY = 0;
            });
            ex += ew + 2;
            button(ex, 44, ew, tr("screen.autoftbq_agent.sketch_color"), () ->
                    color = color == 0xFF202020 ? 0xFFD52D36
                            : color == 0xFFD52D36 ? 0xFF2269CB : 0xFF202020);
        }

        int inputY = extraTools ? 68 : 44;
        label = new EditBox(font, 8, inputY, Math.max(70, width / 3 - 12), 20,
                Component.translatable("screen.autoftbq_agent.sketch_label"));
        label.setMaxLength(100);
        label.setValue(savedLabel);
        label.setHint(Component.translatable("screen.autoftbq_agent.sketch_label_hint"));
        addRenderableWidget(label);
        label.setResponder(value -> savedLabel = value);

        prompt = new EditBox(font, width / 3, inputY, width - width / 3 - 8, 20,
                Component.translatable("screen.autoftbq_agent.sketch_prompt"));
        prompt.setMaxLength(4000);
        prompt.setValue(savedPrompt);
        prompt.setHint(Component.translatable("screen.autoftbq_agent.sketch_prompt_hint"));
        addRenderableWidget(prompt);
        prompt.setResponder(value -> savedPrompt = value);

        int bw = (width - 28) / 4;
        button(8, height - 26, bw, tr("screen.autoftbq_agent.sketch_back"), this::onClose);
        button(12 + bw, height - 26, bw,
                tr(nodes ? "screen.autoftbq_agent.sketch_nodes" : "screen.autoftbq_agent.sketch_shape"),
                this::toggleGenerationFocus);
        button(16 + bw * 2, height - 26, bw,
                tr("screen.autoftbq_agent.sketch_preview"), this::togglePreview);
        send = button(20 + bw * 3, height - 26, bw,
                tr("screen.autoftbq_agent.sketch_generate"), this::submit);
    }

    private void toggleExtraTools() {
        saveInputs();
        extraTools = !extraTools;
        rebuildWidgets();
    }

    private void toggleGenerationFocus() {
        nodes = !nodes;
        saveInputs();
        rebuildWidgets();
    }

    private void saveInputs() {
        if (prompt != null) savedPrompt = prompt.getValue();
        if (label != null) savedLabel = label.getValue();
    }

    private int paperTop() {
        return extraTools ? 94 : 70;
    }

    private double scale() {
        return Math.min((width - 16.0) / 1024,
                Math.max(80.0, height - paperTop() - 40.0) / 640) * zoom;
    }

    private double originX() { return 8 + panX; }
    private double originY() { return paperTop() + panY; }

    private SketchDocument.Point point(double x, double y) {
        return new SketchDocument.Point((x - originX()) / scale(), (y - originY()) / scale());
    }

    private boolean paper(double x, double y) {
        var p = point(x, y);
        return y >= paperTop() && y < height - 40 && x >= 8 && x < width - 8
                && p.x() >= 0 && p.x() < 1024 && p.y() >= 0 && p.y() < 640;
    }

    @Override
    public boolean mouseClicked(double x, double y, int button) {
        if (super.mouseClicked(x, y, button)) return true;
        if (!paper(x, y) || preview) return false;
        if (button == 2) {
            panning = true;
            return true;
        }
        if (button != 0) return false;
        if (tool.equals("text")) {
            if (!label.getValue().isBlank()) {
                add(new SketchDocument.Mark(List.of(point(x, y)), color, 3,
                        label.getValue(), false));
            }
        } else {
            dragging = true;
            stroke.clear();
            stroke.add(point(x, y));
        }
        return true;
    }

    @Override
    public boolean mouseDragged(double x, double y, int button, double dx, double dy) {
        if (panning) {
            panX += dx;
            panY += dy;
            return true;
        }
        if (dragging) {
            if (paper(x, y) && stroke.size() < 4000) stroke.add(point(x, y));
            return true;
        }
        return super.mouseDragged(x, y, button, dx, dy);
    }

    @Override
    public boolean mouseReleased(double x, double y, int button) {
        if (dragging) {
            add(new SketchDocument.Mark(stroke,
                    tool.equals("erase") ? 0xFFFFFFFF : color,
                    tool.equals("erase") ? 24 : 4, "", false));
            stroke.clear();
        }
        dragging = false;
        panning = false;
        return super.mouseReleased(x, y, button);
    }

    @Override
    public boolean mouseScrolled(double x, double y, double delta) {
        if (y >= paperTop() && y < height - 40 && !preview) {
            var p = point(x, y);
            zoom = Math.max(.5, Math.min(4, zoom * Math.pow(1.15, delta)));
            panX = x - 8 - p.x() * scale();
            panY = y - paperTop() - p.y() * scale();
            return true;
        }
        return super.mouseScrolled(x, y, delta);
    }

    private void add(SketchDocument.Mark mark) {
        try {
            DOCUMENT.add(mark);
        } catch (Exception error) {
            message = error.getMessage();
        }
    }

    private void paint(GuiGraphics graphics, SketchDocument.Mark mark) {
        if (mark.clear()) {
            graphics.fill((int) originX(), (int) originY(),
                    (int) (originX() + 1024 * scale()),
                    (int) (originY() + 640 * scale()), 0xFFFFFFFF);
            return;
        }
        if (!mark.text().isEmpty()) {
            var point = mark.points().get(0);
            graphics.pose().pushPose();
            graphics.pose().translate(originX() + point.x() * scale(),
                    originY() + point.y() * scale(), 0);
            graphics.pose().scale((float) (scale() * 2), (float) (scale() * 2), 1);
            graphics.drawString(font, mark.text(), 0, 0, mark.color(), false);
            graphics.pose().popPose();
            return;
        }
        int radius = Math.max(1, (int) Math.ceil(mark.width() * scale() / 2));
        for (int i = 0; i < mark.points().size(); i++) {
            var a = mark.points().get(Math.max(0, i - 1));
            var b = mark.points().get(i);
            int steps = Math.max(1, (int) Math.ceil(Math.max(
                    Math.abs(a.x() - b.x()), Math.abs(a.y() - b.y())) * scale()));
            for (int j = 0; j <= steps; j++) {
                double t = (double) j / steps;
                int px = (int) (originX() + (a.x() + (b.x() - a.x()) * t) * scale());
                int py = (int) (originY() + (a.y() + (b.y() - a.y()) * t) * scale());
                graphics.fill(px - radius, py - radius, px + radius, py + radius, mark.color());
            }
        }
    }

    @Override
    public void render(GuiGraphics graphics, int mouseX, int mouseY, float delta) {
        renderBackground(graphics);
        graphics.drawString(font, title, 8, 6, 0xFFFFFFFF, false);
        graphics.fill(8, paperTop(), width - 8, height - 40, 0xFF606060);
        graphics.enableScissor(8, paperTop(), width - 8, height - 40);
        paint(graphics, new SketchDocument.Mark(List.of(), 0, 0, "", true));
        if (preview && previewTexture != null) {
            graphics.blit(previewTexture, (int) originX(), (int) originY(),
                    (int) (1024 * scale()), (int) (640 * scale()),
                    0, 0, 1024, 640, 1024, 640);
        } else {
            for (var mark : DOCUMENT.marks()) paint(graphics, mark);
            if (!stroke.isEmpty()) {
                paint(graphics, new SketchDocument.Mark(stroke,
                        tool.equals("erase") ? 0xFFFFFFFF : color,
                        tool.equals("erase") ? 24 : 4, "", false));
            }
        }
        graphics.disableScissor();
        send.active = DOCUMENT.hasInk() && !prompt.getValue().isBlank()
                && !BridgeClient.INSTANCE.isBusy();
        graphics.drawString(font, font.plainSubstrByWidth(message, width - 16),
                8, height - 38, 0xFFE1DF9C, false);
        super.render(graphics, mouseX, mouseY, delta);
    }

    private void submit() {
        try {
            if (!DOCUMENT.hasInk() || prompt.getValue().isBlank()
                    || BridgeClient.INSTANCE.isBusy()) return;
            String image = DOCUMENT.pngDataUrl();
            saveInputs();
            minecraft.setScreen(parent);
            BridgeClient.INSTANCE.submitSketch(savedPrompt, image, nodes ? "nodes" : "shape");
        } catch (Exception error) {
            message = tr("screen.autoftbq_agent.sketch_send_failed", error.getMessage());
        }
    }

    private void togglePreview() {
        if (preview) {
            preview = false;
            return;
        }
        try {
            if (previewTexture != null) minecraft.getTextureManager().release(previewTexture);
            byte[] png = java.util.Base64.getDecoder().decode(
                    DOCUMENT.pngDataUrl().split(",", 2)[1]);
            var image = com.mojang.blaze3d.platform.NativeImage.read(
                    new java.io.ByteArrayInputStream(png));
            previewTexture = minecraft.getTextureManager().register(
                    "autoftbq_sketch_preview",
                    new net.minecraft.client.renderer.texture.DynamicTexture(image));
            preview = true;
            zoom = 1;
            panX = panY = 0;
            message = tr("screen.autoftbq_agent.sketch_preview_message");
        } catch (Exception error) {
            message = tr("screen.autoftbq_agent.sketch_preview_failed", error.getMessage());
        }
    }

    @Override
    public void removed() {
        saveInputs();
        if (previewTexture != null) {
            minecraft.getTextureManager().release(previewTexture);
            previewTexture = null;
        }
    }

    @Override
    public void onClose() {
        saveInputs();
        minecraft.setScreen(parent);
    }

    @Override
    public boolean isPauseScreen() {
        return false;
    }
}
