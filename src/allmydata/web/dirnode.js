
var x = 1;

// "#id", ".class"
// "A B" means a B which is a child of A
// in CSS, "#templates { display: none; }" hides stuff
// $("#templates .which").clone() gets you a dom tree fragment
// then frag.find(".section").text(newtext) changes pieces
// then existingnode.empty().append(frag) adds it
function output(text) {
    $("#output").text(text);
}

function setup() {

    $("#mkdir").click(function (event) {x += 1; output("mkdired: "+x);}
                     );
}

$(window).ready(setup);
