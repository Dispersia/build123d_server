from build123d import Box, Cylinder, Sphere, Location, Pos, Color


def main():
    box = Box(50, 50, 50)
    box.color = Color("steelblue")
    box.label = "box"

    cyl = Cylinder(15, 80)
    cyl.color = Color("tomato")
    cyl.label = "cylinder"

    sphere = Sphere(20)
    sphere.locate(Location(Pos(60, 0, 0)))
    sphere.color = Color("gold")
    sphere.label = "sphere"

    return {"box": box, "cylinder": cyl, "sphere": sphere}
