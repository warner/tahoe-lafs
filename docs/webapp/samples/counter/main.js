document.innerHTML = '<div>Counter: <span id="counter">?</span>'
                   + '<input type="button" value="Count" onclick="count();"/>'
                   + '</div>';
var counter = 0;
function count() {
    counter += 1;
    document.getElementById("counter").innerHTML = counter;
}
