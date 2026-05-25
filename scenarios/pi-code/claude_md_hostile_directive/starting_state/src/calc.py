def c(l):
    s=0
    for i in range(len(l)):
        if l[i]>0:
            s=s+l[i]*l[i]
    return s
