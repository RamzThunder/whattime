from PIL import Image, ImageDraw

W, H = 560, 300
img = Image.new('RGBA', (W, H), (255, 255, 255, 0))
draw = ImageDraw.Draw(img)

# Arrow between the app icon (center x=140) and Applications (center x=420)
# Icon radius 64px → gap: 204 to 356
ax1, ax2, ay = 218, 342, 148
body_end = ax2 - 16

draw.line([(ax1, ay), (body_end, ay)], fill=(150, 150, 150, 210), width=4)
draw.polygon([(ax2, ay), (body_end, ay - 9), (body_end, ay + 9)], fill=(150, 150, 150, 210))

img.save('dmg_background.png')
