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
    private String tool = "pen", message = "画圈、箭头和分区即可；文字工具：输入标注后点击纸面。滚轮缩放，中键平移。";
    private int color = 0xFF202020;
    private double zoom = 1, panX, panY;
    private final List<SketchDocument.Point> stroke = new ArrayList<>();
    private boolean dragging, panning, preview;
    private Button send;
    private net.minecraft.resources.ResourceLocation previewTexture;
    public LayoutSketchScreen(Screen parent) { super(Component.literal("自由手绘布局 · 仅新建一个章节")); this.parent = parent; }
    private Button button(int x, int y, int w, String title, Runnable action) {
        return addRenderableWidget(Button.builder(Component.literal(title), b -> {
            if(y==20) preview=false;
            action.run();
        }).bounds(x,y,w,20).build());
    }
    @Override protected void init() {
        int x = 8, tw = Math.min(45, (width-30)/8);
        button(x,20,tw,"画笔", () -> tool="pen"); x+=tw+2;
        button(x,20,tw,"橡皮", () -> tool="erase"); x+=tw+2;
        button(x,20,tw,"文字", () -> tool="text"); x+=tw+2;
        button(x,20,tw,"撤销", DOCUMENT::undo); x+=tw+2;
        button(x,20,tw,"重做", DOCUMENT::redo); x+=tw+2;
        button(x,20,tw,"清空", () -> { try { DOCUMENT.clear(); } catch(Exception e){ message=e.getMessage(); } }); x+=tw+2;
        button(x,20,tw,"适配", () -> {zoom=1; panX=panY=0;}); x+=tw+2;
        button(x,20,tw,"换颜色", () -> color=color==0xFF202020?0xFFD52D36:color==0xFFD52D36?0xFF2269CB:0xFF202020);
        label = new EditBox(font,8,44,Math.max(70,width/3-12),20,Component.literal("标注文字"));
        label.setMaxLength(100); label.setValue(savedLabel); label.setHint(Component.literal("文字标注")); addRenderableWidget(label);
        label.setResponder(value -> savedLabel=value);
        prompt = new EditBox(font,width/3,44,width-width/3-8,20,Component.literal("生成要求"));
        prompt.setMaxLength(4000); prompt.setValue(savedPrompt); prompt.setHint(Component.literal("章节名、任务内容和布局要求")); addRenderableWidget(prompt);
        prompt.setResponder(value -> savedPrompt=value);
        int bw=(width-28)/4;
        button(8,height-26,bw,"返回 Agent",this::onClose);
        button(12+bw,height-26,bw,nodes?"节点优先":"外形优先", () -> {nodes=!nodes; savedPrompt=prompt.getValue();savedLabel=label.getValue();rebuildWidgets();});
        button(16+bw*2,height-26,bw,"预览/编辑", this::togglePreview);
        send=button(20+bw*3,height-26,bw,"按图生成",this::submit);
    }
    private double scale() { return Math.min((width-16.0)/1024, (height-110.0)/640)*zoom; }
    private double originX(){return 8+panX;} private double originY(){return 70+panY;}
    private SketchDocument.Point point(double x,double y){return new SketchDocument.Point((x-originX())/scale(),(y-originY())/scale());}
    private boolean paper(double x,double y){ var p=point(x,y); return y>=70 && y<height-40 && x>=8 && x<width-8 && p.x()>=0 && p.x()<1024 && p.y()>=0 && p.y()<640; }
    @Override public boolean mouseClicked(double x,double y,int b){
        if(super.mouseClicked(x,y,b))return true;
        if(!paper(x,y) || preview)return false;
        if(b==2){panning=true;return true;}
        if(b!=0)return false;
        if(tool.equals("text")){
            if(!label.getValue().isBlank()) add(new SketchDocument.Mark(List.of(point(x,y)),color,3,label.getValue(),false));
        } else {dragging=true;stroke.clear();stroke.add(point(x,y));}
        return true;
    }
    @Override public boolean mouseDragged(double x,double y,int b,double dx,double dy){
        if(panning){panX+=dx;panY+=dy;return true;}
        if(dragging){if(paper(x,y)&&stroke.size()<4000)stroke.add(point(x,y));return true;}
        return super.mouseDragged(x,y,b,dx,dy);
    }
    @Override public boolean mouseReleased(double x,double y,int b){
        if(dragging){add(new SketchDocument.Mark(stroke,tool.equals("erase")?0xFFFFFFFF:color,tool.equals("erase")?24:4,"",false));stroke.clear();}
        dragging=false;panning=false;return super.mouseReleased(x,y,b);
    }
    @Override public boolean mouseScrolled(double x,double y,double delta){
        if(y>=70&&y<height-40&&!preview){var p=point(x,y);zoom=Math.max(.5,Math.min(4,zoom*Math.pow(1.15,delta)));panX=x-8-p.x()*scale();panY=y-70-p.y()*scale();return true;}
        return super.mouseScrolled(x,y,delta);
    }
    private void add(SketchDocument.Mark m){try{DOCUMENT.add(m);}catch(Exception e){message=e.getMessage();}}
    private void paint(GuiGraphics g,SketchDocument.Mark m){
        if(m.clear()){g.fill((int)originX(),(int)originY(),(int)(originX()+1024*scale()),(int)(originY()+640*scale()),0xFFFFFFFF);return;}
        if(!m.text().isEmpty()){
            var p=m.points().get(0);g.pose().pushPose();g.pose().translate(originX()+p.x()*scale(),originY()+p.y()*scale(),0);g.pose().scale((float)(scale()*2),(float)(scale()*2),1);g.drawString(font,m.text(),0,0,m.color(),false);g.pose().popPose();return;
        }
        int r=Math.max(1,(int)Math.ceil(m.width()*scale()/2));
        for(int i=0;i<m.points().size();i++){
            var a=m.points().get(Math.max(0,i-1));var b=m.points().get(i);
            int steps=Math.max(1,(int)Math.ceil(Math.max(Math.abs(a.x()-b.x()),Math.abs(a.y()-b.y()))*scale()));
            for(int j=0;j<=steps;j++){double t=(double)j/steps;int px=(int)(originX()+(a.x()+(b.x()-a.x())*t)*scale()),py=(int)(originY()+(a.y()+(b.y()-a.y())*t)*scale());g.fill(px-r,py-r,px+r,py+r,m.color());}
        }
    }
    @Override public void render(GuiGraphics g,int mx,int my,float dt){
        renderBackground(g);g.drawString(font,title,8,6,0xFFFFFFFF,false);
        g.fill(8,70,width-8,height-40,0xFF606060);g.enableScissor(8,70,width-8,height-40);
        paint(g,new SketchDocument.Mark(List.of(),0,0,"",true));
        if(preview && previewTexture!=null) {
            g.blit(previewTexture,(int)originX(),(int)originY(),(int)(1024*scale()),(int)(640*scale()),0,0,1024,640,1024,640);
        } else {
            for(var m:DOCUMENT.marks())paint(g,m);
            if(!stroke.isEmpty())paint(g,new SketchDocument.Mark(stroke,tool.equals("erase")?0xFFFFFFFF:color,tool.equals("erase")?24:4,"",false));
        }
        g.disableScissor();
        send.active=DOCUMENT.hasInk()&&!prompt.getValue().isBlank()&&!BridgeClient.INSTANCE.isBusy();
        g.drawString(font,font.plainSubstrByWidth(message,width-16),8,height-38,0xFFE1DF9C,false);
        super.render(g,mx,my,dt);
    }
    private void submit(){
        try {
            if(!DOCUMENT.hasInk()||prompt.getValue().isBlank()||BridgeClient.INSTANCE.isBusy())return;
            String image=DOCUMENT.pngDataUrl();
            savedPrompt=prompt.getValue();savedLabel=label.getValue();
            minecraft.setScreen(parent);
            BridgeClient.INSTANCE.submitSketch(savedPrompt,image,nodes?"nodes":"shape");
        }catch(Exception e){message="图片发送失败："+e.getMessage();}
    }
    private void togglePreview() {
        if(preview){preview=false;return;}
        try {
            if(previewTexture!=null)minecraft.getTextureManager().release(previewTexture);
            byte[] png=java.util.Base64.getDecoder().decode(DOCUMENT.pngDataUrl().split(",",2)[1]);
            var image=com.mojang.blaze3d.platform.NativeImage.read(new java.io.ByteArrayInputStream(png));
            previewTexture=minecraft.getTextureManager().register("autoftbq_sketch_preview",new net.minecraft.client.renderer.texture.DynamicTexture(image));
            preview=true;zoom=1;panX=panY=0;message="这是实际发送给多模态模型的完整图片。点击“预览/编辑”继续绘画。";
        } catch(Exception e){message="无法生成预览："+e.getMessage();}
    }
    @Override public void removed(){
        if(prompt!=null){savedPrompt=prompt.getValue();savedLabel=label.getValue();}
        if(previewTexture!=null){minecraft.getTextureManager().release(previewTexture);previewTexture=null;}
    }
    @Override public void onClose(){savedPrompt=prompt.getValue();savedLabel=label.getValue();minecraft.setScreen(parent);}
    @Override public boolean isPauseScreen(){return false;}
}
