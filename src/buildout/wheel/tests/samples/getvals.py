import demo, extdemo
with open('vals', 'w') as f:
    f.write("%s %s" % (demo.value, extdemo.val))
