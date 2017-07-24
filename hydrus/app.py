"""Main route for the applciation."""

import os
import json
from flask import Flask, jsonify, request, abort
from flask_restful import Api, Resource
from hydrus.data.db_models import engine
from sqlalchemy.orm import sessionmaker
from hydrus.metadata.doc_gen import doc_gen
from hydrus.data import crud
from flask_cors import CORS
from contextlib import contextmanager
from flask import appcontext_pushed
from flask import g
import pdb

app = Flask(__name__)
CORS(app)
app.url_map.strict_slashes = False
api = Api(app)


@contextmanager
def set_session(application, DB_SESSION):
    """Set the database session for the app along with context management."""
    def handler(sender, **kwargs):
        g.dbsession = DB_SESSION
    with appcontext_pushed.connected_to(handler, application):
        yield


@contextmanager
def set_doc(application, APIDOC):
    """Set the database session for the app along with context management."""
    def handler(sender, **kwargs):
        g.doc = APIDOC
    with appcontext_pushed.connected_to(handler, application):
        yield


def get_doc():
    """Get the db session for the app with context management."""
    apidoc = getattr(g, 'doc', None)
    if apidoc is None:
        apidoc = doc_gen(API_NAME, HYDRUS_SERVER_URL)
        g.doc = apidoc
    return apidoc


def get_session():
    """Get the db session for the app with context management."""
    session = getattr(g, 'dbsession', None)
    if session is None:
        session = sessionmaker(bind=engine)()
        g.dbsession = session
    return session

HYDRUS_SERVER_URL = os.environ.get("HYDRUS_SERVER_URL", "http://localhost:8080/")
SERVER_URL = os.environ.get("SERVER_URL", HYDRUS_SERVER_URL)

API_NAME = os.environ.get("API_NAME", "api")
API_DOC = doc_gen(API_NAME, HYDRUS_SERVER_URL)
# set_session(app, sessionmaker(bind=engine)())


def validObject(object_):
    """Check if the data passed in POST is of valid format or not."""
    if "@type" in object_:
        return True
    return False


def set_response_headers(resp, ct="application/ld+json", headers=[], status_code=200):
    """Set the response headers."""
    resp.status_code = status_code
    for header in headers:
        resp.headers[list(header.keys())[0]] = header[list(header.keys())[0]]
    resp.headers['Content-type'] = ct
    resp.headers['Link'] = '<' + SERVER_URL + \
        API_NAME+'/vocab>; rel="http://www.w3.org/ns/hydra/core#apiDocumentation"'
    return resp


def hydrafy(object_):
    """Add hydra context to objects."""
    object_["@context"] = "/"+API_NAME+"/contexts/" + object_["@type"] + ".jsonld"
    return object_


class Index(Resource):
    """Class for the EntryPoint."""

    def get(self):
        """Return main entrypoint for the api."""
        return set_response_headers(jsonify(API_DOC.entrypoint.get()))


api.add_resource(Index, "/"+API_NAME+"/", endpoint="api")


class Item(Resource):
    """Handles all operations(GET, POST, PATCH, DELETE) on Items (item can be anything depending upon the vocabulary)."""

    def get(self, id_, type_):
        """GET object with id = id_ from the database."""
        class_type = API_DOC.collections[type_]["collection"].class_.title
        if checkClassOp(class_type, "GET"):
            response = crud.get(id_, class_type, session=get_session())
            if len(response.keys()) == 1:
                status_code = int(list(response.keys())[0])
                return set_response_headers(jsonify(response), status_code=status_code)
            else:
                response["@id"] = '/'+API_NAME+'/'+type_+'/'+str(id_)
                return set_response_headers(jsonify(hydrafy(response)))
        abort(405)

    def post(self, id_, type_):
        """Update object of type<type_> at ID<id_> with new object_ using HTTP POST."""
        class_type = API_DOC.collections[type_]["collection"].class_.title
        if checkClassOp(class_type, "POST"):
            object_ = json.loads(request.data.decode('utf-8'))
            obj_type = getType(class_type, "POST")
            if validObject(object_):
                if object_["@type"] == obj_type:
                    response = crud.update(object_=object_, id_=id_, type_=object_["@type"], session=get_session())
                    object_id = response[list(response.keys())[0]].split("=")[1]
                    headers_ = [{"Location": SERVER_URL+API_NAME+"/"+type_+"/"+str(object_id)}]
                    status_code = int(list(response.keys())[0])
                    return set_response_headers(jsonify(response), headers=headers_, status_code=status_code)
            return set_response_headers(jsonify({400: "Data is not valid"}), status_code=400)
        abort(405)

    def put(self, id_, type_):
        """Add new object_ optional <id_> parameter using HTTP PUT."""
        class_type = API_DOC.collections[type_]["collection"].class_.title
        if checkClassOp(class_type, "PUT"):
            object_ = json.loads(request.data.decode('utf-8'))
            obj_type = getType(class_type, "PUT")
            if validObject(object_):
                if object_["@type"] == obj_type:
                    response = crud.insert(object_=object_, id_=id_, session=get_session())
                    headers_ = [{"Location": SERVER_URL+API_NAME+"/"+type_+"/"+str(id_)}]
                    status_code = int(list(response.keys())[0])
                    return set_response_headers(jsonify(response), headers=headers_, status_code=status_code)
            return set_response_headers(jsonify({400: "Data is not valid"}), status_code=400)
        abort(405)

    def delete(self, id_, type_):
        """Delete object with id=id_ from database."""
        class_type = API_DOC.collections[type_]["collection"].class_.title
        if checkClassOp(class_type, "DELETE"):
            response = crud.delete(id_, class_type, session=get_session())
            status_code = int(list(response.keys())[0])
            return set_response_headers(jsonify(response), status_code=status_code)
        abort(405)


api.add_resource(Item, "/"+API_NAME+"/<string:type_>/<int:id_>", endpoint="item")


class ItemCollection(Resource):
    """Handle operation related to ItemCollection (a collection of items)."""

    def get(self, type_):
        """Retrieve a collection of items from the database."""
        if checkEndpoint("GET", type_):
            # Collections
            if type_ in API_DOC.collections:
                collection = API_DOC.collections[type_]["collection"]
                response = crud.get_collection(API_NAME, collection.class_.title, session=get_session())
                if "members" in response:
                    return set_response_headers(jsonify(hydrafy(response)))
                else:
                    status_code = int(list(response.keys())[0])
                    response = crud.get_collection(API_NAME, type_, session=get_session())
                    return set_response_headers(jsonify(response), status_code=status_code)

            # Non Collection classes
            elif type_ in API_DOC.parsed_classes and type_+"Collection" not in API_DOC.collections:
                response = crud.get_single(type_)
                if len(response.keys()) == 1:
                    status_code = int(list(response.keys())[0])
                    return set_response_headers(jsonify(response), status_code=status_code, session=get_session())
                else:
                    return set_response_headers(jsonify(hydrafy(response)))
        abort(405)

    def put(self, type_):
        """Add item to ItemCollection."""
        if checkEndpoint("PUT", type_):
            object_ = json.loads(request.data.decode('utf-8'))
            # Collections
            if type_ in API_DOC.collections:
                collection = API_DOC.collections[type_]["collection"]
                obj_type = collection.class_.title
                if validObject(object_):
                    if object_["@type"] == obj_type:
                        response = crud.insert(object_=object_, session=get_session())
                        object_id = response[list(response.keys())[0]].split('=')[1]
                        headers_ = [{"Location": SERVER_URL+"api/"+type_+"/"+str(object_id)}]
                        status_code = int(list(response.keys())[0])
                        return set_response_headers(jsonify(response), headers=headers_, status_code=status_code)
                return set_response_headers(jsonify({400: "Data is not valid"}), status_code=400)
            # Non Collection classes
            elif type_ in API_DOC.parsed_classes and type_+"Collection" not in API_DOC.collections:
                obj_type = getType(type_, "PUT")
                if object_["@type"] == obj_type:
                    if validObject(object_):
                        response = crud.insert_single(object_=object_, session=get_session())
                        headers_ = [{"Location": SERVER_URL+API_NAME+"/"+type_+"/"}]
                        status_code = int(list(response.keys())[0])
                        return set_response_headers(jsonify(response), headers=headers_, status_code=status_code)
                return set_response_headers(jsonify({400: "Data is not valid"}), status_code=400)
        abort(405)

    def post(self, type_):
        """Update Non Collection class item."""
        if checkEndpoint("POST", type_):
            object_ = json.loads(request.data.decode('utf-8'))
            if type_ in API_DOC.parsed_classes and type_+"Collection" not in API_DOC.collections:
                obj_type = getType(type_, "POST")
                if validObject(object_):
                    if object_["@type"] == obj_type:
                        response = crud.update_single(object_=object_, session=get_session())
                        headers_ = [{"Location": SERVER_URL+API_NAME+"/"+type_+"/"}]
                        status_code = int(list(response.keys())[0])
                        return set_response_headers(jsonify(response), headers=headers_, status_code=status_code)
                return set_response_headers(jsonify({400: "Data is not valid"}), status_code=400)
        abort(405)

    def delete(self, type_):
        """Delete a non Collection class item."""
        if checkEndpoint("DELETE", type_):
            # No Delete Operation for collections
            if type_ in API_DOC.parsed_classes and type_+"Collection" not in API_DOC.collections:
                response = crud.delete_single(type_, session=get_session())
                status_code = int(list(response.keys())[0])
                return set_response_headers(jsonify(response), status_code=status_code)
        abort(405)


api.add_resource(ItemCollection, "/"+API_NAME+"/<string:type_>",
                 endpoint="item_collection")


class Contexts(Resource):
    """Dynamically genereated contexts."""

    def get(self, category):
        """Return the context for the specified class."""
        if "Collection" in category:
            if category in API_DOC.collections:
                response = {"@context": API_DOC.collections[category]["context"].generate()}
                return set_response_headers(jsonify(response))
            else:
                response = {404: "NOT FOUND"}
                return set_response_headers(jsonify(response), status_code=404)
        else:
            if category in API_DOC.parsed_classes:
                response = {"@context": API_DOC.parsed_classes[category]["context"].generate()}
                return set_response_headers(jsonify(response))
            else:
                response = {404: "NOT FOUND"}
                return set_response_headers(jsonify(response), status_code=404)


api.add_resource(Contexts, "/"+API_NAME+"/contexts/<string:category>.jsonld", endpoint="contexts")


class Vocab(Resource):
    """Vocabulary for Hydra."""

    def get(self):
        """Return the main hydra vocab."""
        return set_response_headers(jsonify(API_DOC.generate()))


api.add_resource(Vocab, "/"+API_NAME+"/vocab", endpoint="vocab")


class Entrypoint(Resource):
    """Hydra EntryPoint."""

    def get(self):
        """Return application main Entrypoint."""
        response = {"@context": API_DOC.entrypoint.context.generate()}
        return set_response_headers(jsonify(response))


api.add_resource(Entrypoint, "/"+API_NAME+"/contexts/EntryPoint.jsonld",
                 endpoint="main_entrypoint")


def checkEndpoint(method, type_):
    """Check if endpoint and method is supported in the API."""
    for endpoint in API_DOC.entrypoint.entrypoint.supportedProperty:
        if type_ == endpoint.name:
            for operation in endpoint.supportedOperation:
                if operation.method == method:
                    return True
    # NOTE: This is checking the EntryPoint object, no need to check class separately.
    # Non collection classes will be present as an endpoint in the Entrypoint object
    return False


def getType(class_type, method):
    """Return the @type of object allowed for POST/PUT."""
    for supportedOp in API_DOC.parsed_classes[class_type]["class"].supportedOperation:
        if supportedOp.method == method:
            return supportedOp.expects.replace("vocab:", "")
    # NOTE: Don't use split, if there are more than one substrings with 'vocab:' not everything will be returned.


def checkClassOp(class_type, method):
    """Check if the Class supports the operation."""
    for supportedOp in API_DOC.parsed_classes[class_type]["class"].supportedOperation:
        if supportedOp.method == method:
            return True
    return False


if __name__ == "__main__":
    # pdb.set_trace()
    app.run(host='127.0.0.1', debug=True, port=8080)
