
var c;
exports.setup = function (endowments) {
    c = endowments.count;
    c(); c();
};

exports.press = function () {
    c();
};

exports.evil = function () {
    document.getElementById("counter").innerHTML = "evil";
};

