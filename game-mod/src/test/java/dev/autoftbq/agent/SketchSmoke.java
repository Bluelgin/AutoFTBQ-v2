package dev.autoftbq.agent;

import dev.autoftbq.agent.client.SketchDocument;
import java.util.List;
import java.util.Base64;
import java.io.ByteArrayInputStream;
import javax.imageio.ImageIO;

public final class SketchSmoke {
    public static void main(String[] args) throws Exception {
        SketchDocument doc = new SketchDocument();
        doc.add(new SketchDocument.Mark(List.of(new SketchDocument.Point(20,20),new SketchDocument.Point(60,20)),0xFFFF0000,4,"",false));
        String png=doc.pngDataUrl();
        var image=ImageIO.read(new ByteArrayInputStream(Base64.getDecoder().decode(png.split(",",2)[1])));
        if(image.getWidth()!=1024||image.getHeight()!=640||image.getRGB(40,20)!=0xFFFF0000)throw new AssertionError("Ink not exported");
        doc.undo();if(doc.hasInk())throw new AssertionError("Undo failed");
        doc.redo();if(!doc.hasInk())throw new AssertionError("Redo failed");
        doc.clear();if(doc.hasInk())throw new AssertionError("Clear failed");
        doc.undo();if(!doc.hasInk())throw new AssertionError("Clear not undoable");
        System.out.println("Freehand PNG/undo/redo smoke passed");
    }
}
