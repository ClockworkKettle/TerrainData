from tkinter import *

def show_entry_fields():
   print("First Name: %s\nLast Name: %s" % (e1.get(), e2.get()))

window = Tk()
window.title("Terrain Generator")
#Column Position
cp = 1;
Label(window, text="Path to DSM").grid(row=0, column = cp)
Label(window, text="Path to AOI").grid(row=1, column = cp)
Label(window, text="Output Path").grid(row=2, column = cp)

e1 = Entry(window)
e2 = Entry(window)
e3 = Entry(window)

e1.grid(row=0, column = 2)
e2.grid(row=1, column = 2)
e3.grid(row=2, column = 2)

b1 = Button(window, text="...").grid(row=0,column = 3, padx=(0,30))
b2 = Button(window, text="...").grid(row=1,column = 3, padx=(0,30))
b3 = Button(window, text="...").grid(row=2,column = 3, padx=(0,30))

Button(window, text='Quit', command=window.quit).grid(row=3, column=0, sticky=W, pady=4)
Button(window, text='Show', command=show_entry_fields).grid(row=3, column=1, sticky=W, pady=4)

mainloop()

